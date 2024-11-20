#!/bin/bash

# Prints the help message
print_help() {
    echo "Usage: ./process_sar_helper.sh -d <directory of sar files> -o <output json file>"
    echo "This script parses the raw system metric logs captured by \"sar\" such as CPU, memory, disk, network, etc."
    echo "\"sar\" is a utility from the sysstat package available on most Linux distros, and is used in this performance setup."
    echo "  -d directory of sar files "
    echo "  -h print help menu "
    echo
    echo "Example: ./process_sar_helper.sh -d <your_log_folder> -o metrics.json"
}

# Parse arguments
while getopts "d:o:h" arg; do
  case $arg in
    d) log_dir=$OPTARG ;;
    o) json_file=$OPTARG ;;
    h) print_help; exit 0 ;;
    *) echo "Invalid option: -$OPTARG"; print_help; exit 1 ;;
  esac
done

if [ -z $log_dir ]; then
    echo "ERROR! the required log directory is not provided."
    print_help
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

json_blob="{"
append_json(){
    key=$1
    val=$2
    if [ "$json_blob" == "{" ]; then
        json_blob="$json_blob\"${key}\": $val"
    else
        json_blob="$json_blob, \"${key}\": $val"
    fi
}


# process cpu
if [ -f $log_dir/cpu.log ]; then
    cpu_values=`grep Average $log_dir/cpu.log | tail -n 1`
    avg_cpu_usr=`echo $cpu_values | awk '{ print $3 }'`
    avg_cpu_sys=`echo $cpu_values | awk '{ print $5 }'`
    avg_cpu_iowait=`echo $cpu_values | awk '{ print $6 }'`
    append_json "avg_cpu_usr" $avg_cpu_usr
    append_json "avg_cpu_sys" $avg_cpu_sys
    append_json "avg_cpu_iowait" $avg_cpu_iowait

    max_cpu_usr=`find_max_with_awk 3 < $log_dir/cpu.log`
    max_cpu_sys=`find_max_with_awk 5 < $log_dir/cpu.log`
    max_cpu_iowait=`find_max_with_awk 6 < $log_dir/cpu.log`
    append_json "max_cpu_usr" $max_cpu_usr
    append_json "max_cpu_sys" $max_cpu_sys
    append_json "max_cpu_iowait" $max_cpu_iowait

else
    echo "WARNING! $log_dir/cpu.log not found."
fi

# process mem
if [ -f $log_dir/mem.log ]; then
    mem_values=`grep Average $log_dir/mem.log | tail -n 1`
    avg_memused=`echo $mem_values | awk '{ print $5 }'`
    avg_memcommit=`echo $mem_values | awk '{ print $9 }'`
    append_json "avg_memused" $avg_memused
    append_json "avg_memcommit" $avg_memcommit

    max_memused=`find_max_with_awk 5 < $log_dir/mem.log`
    max_memcommit=`find_max_with_awk 9 < $log_dir/mem.log`
    append_json "max_memused" $max_memused
    append_json "max_memcommit" $max_memcommit
else
    echo "WARNING! $log_dir/mem.log not found."
fi


# process network socket
if [ -f $log_dir/network.sock.log ]; then
    socket_values=`grep Average $log_dir/network.sock.log | tail -n 1`
    avg_network_totsck=`echo $socket_values | awk '{ print $2 }'`
    avg_network_tcp_tw=`echo $socket_values | awk '{ print $7 }'`
    append_json "avg_network_totsck" $avg_network_totsck
    append_json "avg_network_tcp_tw" $avg_network_tcp_tw

    max_network_totsck=`find_max_with_awk 2 < $log_dir/network.sock.log`
    max_network_tcp_tw=`find_max_with_awk 7 < $log_dir/network.sock.log`
    append_json "max_network_totsck" $max_network_totsck
    append_json "max_network_tcp_tw" $max_network_tcp_tw
else
    echo "WARNING! $log_dir/network.sock.log not found."
fi

# process network (etho) device
if [ -f $log_dir/network.dev.log ]; then
    dev=eth0
    grep $dev $log_dir/network.dev.log > $log_dir/network.dev.${dev}.log

    avg_values=`grep Average $log_dir/network.dev.${dev}.log | tail -n 1`
    avg_rxkBps=`echo $avg_values | awk '{ print $5 }'`
    avg_txkBps=`echo $avg_values | awk '{ print $6 }'`
    avg_ifutil=`echo $avg_values | awk '{ print $10 }'`
    append_json "avg_${dev}_rxkBps" $avg_rxkBps
    append_json "avg_${dev}_txkBps" $avg_txkBps
    append_json "avg_${dev}_ifutil" $avg_ifutil

    max_rxkBps=`find_max_with_awk 5 < $log_dir/network.dev.${dev}.log`
    max_txkBps=`find_max_with_awk 6 < $log_dir/network.dev.${dev}.log`
    max_ifutil=`find_max_with_awk 10 < $log_dir/network.dev.${dev}.log`
    append_json "max_${dev}_rxkBps" $max_rxkBps
    append_json "max_${dev}_txkBps" $max_txkBps
    append_json "max_${dev}_ifutil" $max_ifutil
else
    echo "WARNING! $log_dir/network.dev.log not found."
fi

# process disk (vda|sda) device
if [ -f $log_dir/disk.log ]; then
    device=`grep Average $log_dir/disk.log | grep -E "sda|vda" | awk '{ print $NF }'`
    grep $device $log_dir/disk.log > $log_dir/disk.$device.log

    device_values=`grep Average $log_dir/disk.$device.log | tail -n 1`
    avg_tps=`echo $device_values | awk '{ print $2 }'`
    avg_rkBps=`echo $device_values | awk '{ print $3 }'`
    avg_wkBps=`echo $device_values | awk '{ print $4 }'`
    avg_aqu_sz=`echo $device_values | awk '{ print $7 }'`
    avg_await=`echo $device_values | awk '{ print $8 }'`
    avg_util=`echo $device_values | awk '{ print $9 }'`
    append_json "avg_disk_${device}_tps" $avg_tps
    append_json "avg_disk_${device}_rkBps" $avg_rkBps
    append_json "avg_disk_${device}_wkBps" $avg_wkBps
    append_json "avg_disk_${device}_aqu_sz" $avg_aqu_sz
    append_json "avg_disk_${device}_await" $avg_await
    append_json "avg_disk_${device}_util" $avg_util

    max_tps=`find_max_with_awk 2 < $log_dir/disk.$device.log`
    max_rkBps=`find_max_with_awk 3 < $log_dir/disk.$device.log`
    max_wkBps=`find_max_with_awk 4 < $log_dir/disk.$device.log`
    max_aqu_sz=`find_max_with_awk 7 < $log_dir/disk.$device.log`
    max_await=`find_max_with_awk 8 < $log_dir/disk.$device.log`
    max_util=`find_max_with_awk 9 < $log_dir/disk.$device.log`
    append_json "max_disk_${device}_tps" $max_tps
    append_json "max_disk_${device}_rkBps" $max_rkBps
    append_json "max_disk_${device}_wkBps" $max_wkBps
    append_json "max_disk_${device}_aqu_sz" $max_aqu_sz
    append_json "max_disk_${device}_await" $max_await
    append_json "max_disk_${device}_util" $max_util
else
    echo "WARNING! $log_dir/disk.log not found."
fi

json_blob="${json_blob}}"
echo $json_blob > ${log_dir}/${json_file}
