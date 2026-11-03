#!/bin/bash
# detect_nic.sh — 自动探测本机通信网卡，供 PD 各启动脚本 source。
#
# 探测内容：
#   SOCKET_IFNAME  TCP 通信网卡（GLOO/NCCL/MCCL 的 *_SOCKET_IFNAME）
#   LOCAL_IP       该网卡上的 IPv4（worker 上报给 router 用）
#   HCA_LIST       IB HCA（*_IB_HCA / *_HCA_LIST / --disaggregation-ib-device）
#
# 三个变量都可用同名环境变量覆盖；探测不到时不设置，下游脚本回退到自己的默认值。
# 不依赖 iproute2：镜像里没有 ip 命令，改用 python3 标准库 + /sys + /proc 探测；
# python3 不可用时才退回 ip route get / ip -4 addr / hostname -I。
# 选择顺序：默认路由网卡 > HCA_LIST 对应网卡 > 第一个 UP 且有 IPv4 的网卡。
# 服务 IP（router/decode 互相访问）优先走默认路由网段，HCA 网段可能只有 RDMA 通。
# HCA 算法抄自原 run.sh 的 pd_ib_hca()：
#   候选 = mx-smi 拓扑中与任一 GPU 为 PIX/PXB 的 NIC ∩ 速率 >= 400Gb/s ∩ 端口 ACTIVE

# 每个容器只探测一次：start 脚本探测后 export，服务脚本 source 时直接复用
if [ "${_DETECT_NIC_DONE:-}" = 1 ]; then
    return 0 2>/dev/null || exit 0
fi
export _DETECT_NIC_DONE=1

pd_ib_hca() {
    local mode="${1:-}" n rec active="" awks='
        /^ *GPU0 /{for(i=1;i<=NF;i++)if($i~/^GPU[0-9]+$/)ng++}
        /^ *NIC[0-9]+:/{sub(/:/,"",$1);nic[$1]=$2}
        /^ *NIC[0-9]+ /{for(i=2;i<=ng+1;i++)if($i=="PIX"||$i=="PXB"){good[$1]=1;break}}
        END{for(k in nic){n=substr(k,4)+0;if(n>max)max=n}
            for(i=0;i<=max;i++){k="NIC"i;if(good[k])printf"%s ",nic[k]}print""}'
    # 候选 = 拓扑 PIX/PXB ∩ 端口 ACTIVE
    rec="$(mx-smi topo -n 2>/dev/null | awk "$awks" | sed 's/ $//')"
    for n in $rec; do
        # 只用速率 >=400Gb/s 的网卡(200G HDR 等低速口直接排除,如 mlx5_20)
        rate="$(awk '{print $1}' "/sys/class/infiniband/$n/ports/1/rate" 2>/dev/null)"
        [[ -n "${rate}" && "${rate}" -ge 400 ]] || continue
        [[ "$(cat "/sys/class/infiniband/$n/ports/1/state" 2>/dev/null)" == 4:* ]] && active="$active $n"
    done
    active="${active# }"
    if [[ "$mode" =~ ^(-d|--detail|detail)$ ]]; then
        printf '%-10s %-22s %-8s %-10s %-6s %s\n' NIC RATE STATE NETDEV NUMA PD
        for d in /sys/class/infiniband/mlx5_*; do
            [ -d "$d" ] || continue
            n="${d##*/}"
            st="$(sed -n 's/^[0-9]*: *//p' "$d/ports/1/state" 2>/dev/null)"
            [[ " $active " == *" $n "* ]] && mark=OK || mark=-
            printf '%-10s %-22s %-8s %-10s %-6s %s\n' \
                "$n" "$(cat "$d/ports/1/rate" 2>/dev/null)" "${st:-?}" \
                "$(ls "$d/device/net/" 2>/dev/null | tr '\n' ' ')" "$(cat "$d/device/numa_node" 2>/dev/null)" "$mark"
        done
    else
        echo "${active// /,}"
    fi
}

# ---- IB HCA（先探测，socket 选择会用它做网卡优先级）----
if [ -z "${HCA_LIST:-}" ] && command -v mx-smi >/dev/null 2>&1; then
    HCA_LIST="$(pd_ib_hca)"
fi

# ---- socket 网卡 / 本机 IP ----
# 输出 iface= / ip= / source= / candidates=，不走 ip 命令
_detect_out=""
if command -v python3 >/dev/null 2>&1; then
    _detect_out="$(python3 - "${HCA_LIST:-}" "${SOCKET_IFNAME:-}" "${LOCAL_IP:-}" <<'PY'
import fcntl
import os
import socket
import struct
import sys

hca_arg = sys.argv[1].strip() if len(sys.argv) > 1 else ""
iface_in = sys.argv[2].strip() if len(sys.argv) > 2 else ""
ip_in = sys.argv[3].strip() if len(sys.argv) > 3 else ""

SIOCGIFADDR = 0x8915
VIRT_PREFIX = ("docker", "veth", "br-", "virbr", "tun", "tap", "kube", "cni",
               "flannel", "cali", "weave", "dummy", "lxc")


def ip_of(iface):
    if not iface:
        return ""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        req = struct.pack("256s", iface.encode("utf-8")[:15])
        return socket.inet_ntoa(fcntl.ioctl(s.fileno(), SIOCGIFADDR, req)[20:24])
    except (OSError, ValueError):
        return ""
    finally:
        s.close()


def is_up(iface):
    base = "/sys/class/net/" + iface
    try:
        with open(base + "/operstate") as f:
            if f.read().strip() in ("down", "notpresent", "lowerlayerdown"):
                return False
    except OSError:
        pass
    try:
        with open(base + "/carrier") as f:
            if f.read().strip() == "0":
                return False
    except OSError:
        pass
    return True


def is_virtual(name):
    return name == "lo" or name.startswith(VIRT_PREFIX)


def default_iface():
    # 无 ip 命令时从 /proc/net/route 找默认路由
    try:
        with open("/proc/net/route") as f:
            next(f)
            for line in f:
                p = line.split()
                if len(p) > 3 and p[1] == "00000000" and (int(p[3], 16) & 0x1):
                    return p[0]
    except (OSError, ValueError):
        pass
    return ""


def hca_netdevs(hcas):
    # 只在 HCA_LIST 明确时按 HCA 选网卡；探测不到 HCA 时不猜
    order = hcas.replace(",", " ").split()
    out = []
    for h in order:
        try:
            for n in sorted(os.listdir("/sys/class/infiniband/%s/device/net" % h)):
                if n not in out:
                    out.append(n)
        except OSError:
            continue
    return out


cands = []
for _, name in socket.if_nameindex():
    if is_virtual(name) or not is_up(name):
        continue
    ip = ip_of(name)
    if ip and all(n != name for n, _ in cands):
        cands.append((name, ip))

route = default_iface()
hca_nets = hca_netdevs(hca_arg)


def find(name):
    for n, ip in cands:
        if n == name:
            return (n, ip)
    return None


choice = None
source = ""
if iface_in:
    choice = (iface_in, ip_in or ip_of(iface_in))
    source = "override"
elif ip_in:
    owner = ""
    for n, ip in cands:
        if ip == ip_in:
            owner = n
            break
    choice = (owner, ip_in)
    source = "override"
else:
    # 服务地址优先默认路由网卡：HCA 网段可能跨机不通
    hit = find(route)
    if hit:
        choice, source = hit, "route"
    if not choice:
        for n in hca_nets:
            hit = find(n)
            if hit:
                choice, source = hit, "hca"
                break
    if not choice:
        for n, ip in cands:
            if not ip.startswith("169.254."):
                choice, source = (n, ip), "fallback"
                break
    if not choice and cands:
        choice, source = cands[0], "fallback"

chosen_iface = choice[0] if choice else ""
chosen_ip = choice[1] if choice else ""


def mark(name, ip):
    tags = []
    if name in hca_nets:
        tags.append("hca")
    if name == route:
        tags.append("route")
    return "%s=%s%s" % (name, ip, "(" + ",".join(tags) + ")" if tags else "")


print("iface=" + chosen_iface)
print("ip=" + chosen_ip)
print("source=" + source)
print("candidates=" + " ".join(mark(n, ip) for n, ip in cands))
PY
)"
fi

_detect_value() {
    printf '%s\n' "$_detect_out" | sed -n "s/^$1=//p" | head -n 1
}

if [ -z "${SOCKET_IFNAME:-}" ]; then
    SOCKET_IFNAME="$(_detect_value iface)"
fi
if [ -z "${LOCAL_IP:-}" ]; then
    LOCAL_IP="$(_detect_value ip)"
fi
_DETECT_SOURCE="$(_detect_value source)"
_DETECT_CANDIDATES="$(_detect_value candidates)"

# Python 探测不到时依次退回（顺序参考线上取 IP 脚本）：
#   ip route get 8.8.8.8 的 src/dev  ->  ip -4 -o addr  ->  hostname -I
# 不静默回退 127.0.0.1：worker 上报 loopback 会让 master 连错，宁可显式失败。
if command -v ip >/dev/null 2>&1; then
    _route_out="$(ip -o route get 8.8.8.8 2>/dev/null)"
    if [ -z "${SOCKET_IFNAME:-}" ]; then
        SOCKET_IFNAME="$(printf '%s\n' "$_route_out" | awk '{
            for (i = 1; i <= NF; i++) if ($i == "dev") { print $(i + 1); exit }
        }')"
        [ -n "${SOCKET_IFNAME:-}" ] && [ -z "${_DETECT_SOURCE:-}" ] && _DETECT_SOURCE="ip-route"
    fi
    if [ -z "${LOCAL_IP:-}" ]; then
        LOCAL_IP="$(printf '%s\n' "$_route_out" | sed -n 's/.* src \([0-9.]*\).*/\1/p' | head -n1)"
        [ -n "${LOCAL_IP:-}" ] && [ -z "${_DETECT_SOURCE:-}" ] && _DETECT_SOURCE="ip-route"
    fi
fi
if [ -z "${LOCAL_IP:-}" ] && [ -n "${SOCKET_IFNAME:-}" ] && command -v ip >/dev/null 2>&1; then
    LOCAL_IP="$(ip -o -4 addr show dev "$SOCKET_IFNAME" scope global 2>/dev/null |
        awk '{ sub(/\/.*/, "", $4); print $4; exit }')"
    [ -n "${LOCAL_IP:-}" ] && [ -z "${_DETECT_SOURCE:-}" ] && _DETECT_SOURCE="ip-addr"
fi
if [ -z "${LOCAL_IP:-}" ] && command -v hostname >/dev/null 2>&1; then
    for _h in $(hostname -I 2>/dev/null); do
        case "$_h" in
            *:*|127.*|169.254.*) continue ;;
        esac
        LOCAL_IP="$_h"
        [ -z "${_DETECT_SOURCE:-}" ] && _DETECT_SOURCE="hostname -I"
        break
    done
fi

# ---- 导出 socket 网卡 ----
if [ -n "${SOCKET_IFNAME:-}" ]; then
    export SOCKET_IFNAME
    export NCCL_SOCKET_IFNAME="$SOCKET_IFNAME"
    export GLOO_SOCKET_IFNAME="$SOCKET_IFNAME"
    export MCCL_SOCKET_IFNAME="$SOCKET_IFNAME"
    export MXSHMEM_BOOTSTRAP_UID_SOCK_IFNAME="$SOCKET_IFNAME"
    export NVSHMEM_BOOTSTRAP_UID_SOCK_IFNAME="$SOCKET_IFNAME"
fi

if [ -n "${LOCAL_IP:-}" ]; then
    export LOCAL_IP
fi

# ---- IB HCA ----
if [ -n "${HCA_LIST:-}" ]; then
    export HCA_LIST
    export MCCL_IB_HCA="$HCA_LIST"
    export MXSHMEM_HCA_LIST="$HCA_LIST"
    export NCCL_IB_HCA="$HCA_LIST"
    export NVSHMEM_HCA_LIST="$HCA_LIST"
fi

echo "[detect_nic] host=$(hostname 2>/dev/null || cat /etc/hostname 2>/dev/null) SOCKET_IFNAME=${SOCKET_IFNAME:-<未探测>} LOCAL_IP=${LOCAL_IP:-<未探测>} HCA_LIST=${HCA_LIST:-<未探测>} source=${_DETECT_SOURCE:-<无>}"
[ -n "${_DETECT_CANDIDATES:-}" ] && echo "[detect_nic] candidates: ${_DETECT_CANDIDATES}"
[ -n "${SOCKET_IFNAME:-}" ] || echo "[detect_nic] WARN: 未探测到 socket 网卡，请用 SOCKET_IFNAME 指定" >&2
[ -n "${LOCAL_IP:-}" ]     || echo "[detect_nic] WARN: 未探测到本机 IP，请用 LOCAL_IP 指定" >&2
[ -n "${HCA_LIST:-}" ]     || echo "[detect_nic] WARN: 未探测到 >=400Gb/s ACTIVE 的 HCA，请用 HCA_LIST 指定" >&2
true
