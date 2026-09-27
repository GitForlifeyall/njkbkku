FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y \
    build-essential \
    flex \
    bison \
    libssl-dev \
    libelf-dev \
    bc \
    git \
    dwarves \
    ca-certificates \
    curl \
    cpio

WORKDIR /build
RUN git clone --depth 1 -b linux-msft-wsl-6.6.y https://github.com/microsoft/WSL2-Linux-Kernel.git

WORKDIR /build/WSL2-Linux-Kernel
RUN cp Microsoft/config-wsl .config && \
    scripts/config --enable CONFIG_ANDROID && \
    scripts/config --enable CONFIG_ANDROID_BINDER_IPC && \
    scripts/config --enable CONFIG_ANDROID_BINDERFS && \
    scripts/config --set-str CONFIG_ANDROID_BINDER_DEVICES "binder,hwbinder,vndbinder" && \
    scripts/config --enable CONFIG_ASHMEM

CMD make -j$(nproc) bzImage && cp arch/x86/boot/bzImage /out/bzImage
