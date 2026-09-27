#!/usr/bin/env bash
set -e

echo "=== 1. Updating packages and installing build tools ==="
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq build-essential flex bison libssl-dev libelf-dev bc git dwarves ca-certificates curl cpio libncurses-dev

echo "=== 2. Cloning Microsoft WSL2 Linux Kernel source ==="
mkdir -p /build
cd /build
if [ ! -d "WSL2-Linux-Kernel" ]; then
    git clone --depth 1 -b linux-msft-wsl-6.6.y https://github.com/microsoft/WSL2-Linux-Kernel.git
fi
cd WSL2-Linux-Kernel

echo "=== 3. Configuring Kernel with Android Core, Codec2, and BinderFS ==="
cp Microsoft/config-wsl .config
scripts/config --enable CONFIG_ANDROID
scripts/config --enable CONFIG_ANDROID_BINDER_IPC
scripts/config --enable CONFIG_ANDROID_BINDERFS
scripts/config --set-str CONFIG_ANDROID_BINDER_DEVICES "binder,hwbinder,vndbinder"
scripts/config --enable CONFIG_MEMFD_CREATE
scripts/config --enable CONFIG_PSI
scripts/config --enable CONFIG_STAGING
scripts/config --enable CONFIG_ASHMEM
scripts/config --enable CONFIG_DMABUF_HEAPS
scripts/config --enable CONFIG_DMABUF_HEAPS_SYSTEM

echo "=== 3b. Configuring Kernel with Built-in Android Networking, IPsec, and BPF ==="
scripts/config --enable CONFIG_NET_KEY
scripts/config --enable CONFIG_XFRM
scripts/config --enable CONFIG_XFRM_USER
scripts/config --enable CONFIG_XFRM_INTERFACE
scripts/config --enable CONFIG_INET_ESP
scripts/config --enable CONFIG_INET_AH
scripts/config --enable CONFIG_INET_IPCOMP
scripts/config --enable CONFIG_INET_XFRM_MODE_TRANSPORT
scripts/config --enable CONFIG_INET_XFRM_MODE_TUNNEL
scripts/config --enable CONFIG_NETFILTER_XT_MATCH_QUOTA
scripts/config --enable CONFIG_NETFILTER_XT_MATCH_QUOTA2
scripts/config --enable CONFIG_NETFILTER_XT_MATCH_OWNER
scripts/config --enable CONFIG_NETFILTER_XT_MATCH_SOCKET
scripts/config --enable CONFIG_NETFILTER_XT_MATCH_CONNTRACK
scripts/config --enable CONFIG_NETFILTER_XT_MATCH_BPF
scripts/config --enable CONFIG_NETFILTER_XT_TARGET_IDLETIMER
scripts/config --enable CONFIG_NET_CLS_ACT
scripts/config --enable CONFIG_NET_CLS_BPF
scripts/config --enable CONFIG_NET_ACT_BPF
scripts/config --enable CONFIG_NET_SCH_INGRESS
scripts/config --enable CONFIG_BPF
scripts/config --enable CONFIG_BPF_SYSCALL
scripts/config --enable CONFIG_BPF_JIT
scripts/config --enable CONFIG_CGROUP_BPF

echo "=== 3c. Configuring Kernel with Bluetooth Virtualization (VHCI) & HID ==="
scripts/config --enable CONFIG_BT
scripts/config --enable CONFIG_BT_BREDR
scripts/config --enable CONFIG_BT_LE
scripts/config --enable CONFIG_BT_RFCOMM
scripts/config --enable CONFIG_BT_BNEP
scripts/config --enable CONFIG_BT_HIDP
scripts/config --enable CONFIG_BT_HCIBTUSB
scripts/config --enable CONFIG_BT_HCIVHCI
scripts/config --enable CONFIG_UHID

echo "=== 3d. Configuring Kernel with Virtual ALSA Audio Drivers ==="
scripts/config --enable CONFIG_SOUND
scripts/config --enable CONFIG_SND
scripts/config --enable CONFIG_SND_HRTIMER
scripts/config --enable CONFIG_SND_DYNAMIC_MINORS
scripts/config --enable CONFIG_SND_SUPPORT_OLD_API
scripts/config --enable CONFIG_SND_PROC_FS
scripts/config --enable CONFIG_SND_VERBOSE_PROCFS
scripts/config --enable CONFIG_SND_SEQUENCER
scripts/config --enable CONFIG_SND_SEQ_DUMMY
scripts/config --enable CONFIG_SND_DUMMY
scripts/config --enable CONFIG_SND_ALOOP
scripts/config --enable CONFIG_SND_VIRMIDI

echo "=== 3e. Configuring IPv6 Routing for Android ==="
scripts/config --enable CONFIG_IPV6_ROUTER_PREF
scripts/config --enable CONFIG_IPV6_ROUTE_INFO
scripts/config --enable CONFIG_IPV6_MULTIPLE_TABLES
scripts/config --enable CONFIG_IPV6_SUBTREES

scripts/config --disable CONFIG_DEBUG_INFO_BTF

echo "=== 3f. Updating default configuration non-interactively ==="
make olddefconfig

echo "=== 4. Compiling Kernel (bzImage & modules) with $(nproc) cores ==="
make -j$(nproc) WERROR=0 bzImage
make -j$(nproc) modules
make modules_install

echo "=== 5. Copying bzImage to Windows Host ==="
mkdir -p /mnt/c/Users/khann/wsl-kernel
cp arch/x86/boot/bzImage /mnt/c/Users/khann/wsl-kernel/bzImage-audio
cp arch/x86/boot/bzImage /mnt/c/Users/khann/wsl-kernel/bzImage 2>/dev/null || true

echo "=== Kernel compilation complete! ==="

