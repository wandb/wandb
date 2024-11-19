#!/bin/bash

log_dir=$1
if [ -z $log_dir ]; then
    echo "ERROR! the required log directory is not provided."
    echo "e.g. ./process_sar.sh logs"
    exit 1
fi

if [ ! -d $log_dir ]; then
    echo "ERROR! the directory $log_dir does not exist!"
    exit 1
fi

find_max_with_awk() {
    local column=$1  # Get the column number as the first argument
    awk -v col="$column" 'NR > 2 {if ($col+0 > max) max=$col} END {if(max==""){print 0}else{print max}}'
}


echo "Processing log files in $log_dir"

# process cpu
if [ -f $log_dir/cpu.log ]; then
    cpu_values=`grep Average $log_dir/cpu.log | tail -n 1`
    avg_cpu_usr=`echo $cpu_values | awk '{ print $3 }'`
    avg_cpu_sys=`echo $cpu_values | awk '{ print $5 }'`
    avg_cpu_iowait=`echo $cpu_values | awk '{ print $6 }'`
    echo "{"avg_cpu_usr":$avg_cpu_usr, "avg_cpu_sys":$avg_cpu_sys, "avg_cpu_iowait":$avg_cpu_iowait}"

    max_cpu_usr=`find_max_with_awk 3 < $log_dir/cpu.log`
    max_cpu_sys=`find_max_with_awk 5 < $log_dir/cpu.log`
    max_cpu_iowait=`find_max_with_awk 6 < $log_dir/cpu.log`
    echo "{"max_cpu_usr":$max_cpu_usr, "max_cpu_sys":$max_cpu_sys, "max_cpu_iowait":$max_cpu_iowait}"
else
    echo "WARNING! $log_dir/cpu.log not found."
fi

# process mem
if [ -f $log_dir/mem.log ]; then
    mem_values=`grep Average $log_dir/mem.log | tail -n 1`
    avg_memused=`echo $mem_values | awk '{ print $5 }'`
    avg_memcommit=`echo $mem_values | awk '{ print $9 }'`
    echo "{"avg_memused":$avg_memused, "avg_memcommit":$avg_memcommit}"

    max_memused=`find_max_with_awk 5 < $log_dir/mem.log`
    max_memcommit=`find_max_with_awk 9 < $log_dir/mem.log`
    echo "{"max_memused":$max_memused, "max_memcommit":$max_memcommit}"
else
    echo "WARNING! $log_dir/mem.log not found."
fi


# process network socket
if [ -f $log_dir/network.sock.log ]; then
    socket_values=`grep Average $log_dir/network.sock.log | tail -n 1`
    avg_totsck=`echo $socket_values | awk '{ print $2 }'`
    avg_tcp_tw=`echo $socket_values | awk '{ print $7 }'`
    echo "{"avg_network_totsck":$avg_totsck, "avg_network_tcp_tw":$avg_tcp_tw}"

    max_totsck=`find_max_with_awk 2 < $log_dir/network.sock.log`
    max_tcp_tw=`find_max_with_awk 7 < $log_dir/network.sock.log`
    echo "{"max_network_totsck":$max_totsck, "max_network_tcp_tw":$max_tcp_tw}"
else
    echo "WARNING! $log_dir/network.sock.log not found."
fi

# process network (etho) device
if [ -f $log_dir/network.dev.log ]; then
    grep eth0 $log_dir/network.dev.log > $log_dir/network.dev.eth0.log

    etho_values=`grep Average $log_dir/network.dev.eth0.log | tail -n 1`
    avg_rxkBps=`echo $etho_values | awk '{ print $5 }'`
    avg_txkBps=`echo $etho_values | awk '{ print $6 }'`
    avg_ifutil=`echo $etho_values | awk '{ print $10 }'`
    echo "{"avg_eth0_rxkBps":$avg_rxkBps, "avg_eth0_txkBps":$avg_txkBps, "avg_eth0_ifutil":$avg_ifutil}"

    max_rxkBps=`find_max_with_awk 5 < $log_dir/network.dev.eth0.log`
    max_txkBps=`find_max_with_awk 6 < $log_dir/network.dev.eth0.log`
    max_ifutil=`find_max_with_awk 10 < $log_dir/network.dev.eth0.log`
    echo "{"max_eth0_rxkBps":$max_rxkBps, "max_eth0_txkBps":$max_txkBps, "max_eth0_ifutil":$max_ifutil}"

else
    echo "WARNING! $log_dir/network.dev.log not found."
fi   

# process disk (vda|sda) device
if [ -f $log_dir/disk.log ]; then
    device=`grep Average $log_dir/disk.log | grep -E "sda|vda" | awk '{ print $NF }'`
    #echo "process_sar_helper.sh: Parsing disk IO metrics with: $device"
    grep $device $log_dir/disk.log > $log_dir/disk.$device.log

    device_values=`grep Average $log_dir/disk.$device.log | tail -n 1`
    avg_tps=`echo $device_values | awk '{ print $2 }'`
    avg_rkBps=`echo $device_values | awk '{ print $3 }'`
    avg_wkBps=`echo $device_values | awk '{ print $4 }'`
    avg_aqu_sz=`echo $device_values | awk '{ print $7 }'`
    avg_await=`echo $device_values | awk '{ print $8 }'`
    avg_util=`echo $device_values | awk '{ print $9 }'`
    echo "{"avg_disk_${device}_tps":$avg_tps, "avg_disk_${device}_rkBps":$avg_rkBps, "avg_disk_${device}_wkBps":$avg_wkBps, "avg_disk_${device}_aqu_sz":$avg_aqu_sz, "avg_disk_${device}_await":$avg_await, "avg_disk_${device}_util":$avg_util}"

    max_tps=`find_max_with_awk 2 < $log_dir/disk.$device.log`
    max_rkBps=`find_max_with_awk 3 < $log_dir/disk.$device.log`
    max_wkBps=`find_max_with_awk 4 < $log_dir/disk.$device.log`
    max_aqu_sz=`find_max_with_awk 7 < $log_dir/disk.$device.log`
    max_await=`find_max_with_awk 8 < $log_dir/disk.$device.log`
    max_util=`find_max_with_awk 9 < $log_dir/disk.$device.log`
    echo "{"max_disk_${device}_tps":$max_tps, "max_disk_${device}_rkBps":$max_rkBps, "max_disk_${device}_wkBps":$max_wkBps, "max_disk_${device}_aqu_sz":$max_aqu_sz, "max_disk_${device}_await":$max_await, "max_disk_${device}_util":$max_util}"

else
    echo "WARNING! $log_dir/disk.log not found."
fi   



