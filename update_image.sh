#!/bin/bash
set -e
CID=$(docker create redroid-instagram:ndk)
SRC="/mnt/c/Users/khann/OneDrive/Documents/Projects/insta uploader/ytuploader/apks/native_libs/lib"

docker cp "$SRC/x86_64/libconscrypt_gmscore_jni.so" ${CID}:/system/lib64/libconscrypt_gmscore_jni.so
docker cp "$SRC/x86/libconscrypt_gmscore_jni.so" ${CID}:/system/lib/libconscrypt_gmscore_jni.so

docker commit ${CID} redroid-instagram:ndk
docker rm ${CID}
echo "Image updated successfully!"
