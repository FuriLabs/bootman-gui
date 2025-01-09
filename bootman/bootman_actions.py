import subprocess
from pathlib import Path
import os

def is_mounted(mount_point):
    """Check if a specific mount point is mounted."""
    try:
        with open('/proc/mounts', 'r') as f:
            return any(mount_point in line for line in f)
    except Exception:
        return False

def mount_partition(password):
    """
    Mount the FuriOS persist partition.

    Args:
        password (str): sudo password

    Returns:
        tuple: (success_boolean, message)
    """
    try:
        # Create mount point
        mkdir_cmd = f'echo {password} | sudo -S mkdir -p /furios_persist'
        result = subprocess.run(mkdir_cmd, shell=True, text=True, capture_output=True)
        if result.returncode != 0:
            return False, f"Failed to create mount point: {result.stderr}"

        # Mount partition
        mount_cmd = f'echo {password} | sudo -S mount /dev/disk/by-partlabel/furios_persist /furios_persist'
        result = subprocess.run(mount_cmd, shell=True, text=True, capture_output=True)

        if result.returncode != 0:
            return False, f"Failed to mount partition: {result.stderr}"

        # Create bootman work directory
        bootman_mkdir_cmd = f'echo {password} | sudo -S mkdir -p /furios_persist/bootman'
        result = subprocess.run(bootman_mkdir_cmd, shell=True, text=True, capture_output=True)

        if result.returncode == 0:
            return True, "Successfully setup the partition"
        else:
            return False, f"Failed to setup the partition: {result.stderr}"
    except Exception as e:
        return False, f"Error mounting partition: {str(e)}"

def get_partition_size(partition_name, password=None):
    """
    Get the size of a specific LVM partition.

    Args:
        partition_name (str): Name of the partition
        password (str, optional): sudo password

    Returns:
        str: Partition size or "Unknown"
    """
    try:
        cmd = f'echo {password} | sudo -S lvdisplay /dev/droidian/{partition_name}'
        result = subprocess.run(cmd, shell=True, text=True, capture_output=True)
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if "LV Size" in line:
                    size = line.split()[2]
                    unit = line.split()[3]
                    return f"{size}{unit}"
        return "Unknown"
    except Exception:
        return "Unknown"

def process_partition_name(partition_name):
    """
    Convert raw partition name to a more readable format.

    Args:
        partition_name (str): Raw partition name

    Returns:
        str: Formatted partition name
    """
    if partition_name == 'droidian-rootfs':
        return 'FuriOS rootfs'

    if partition_name.startswith('droidian-'):
        name = partition_name.replace('droidian-', '')
        words = name.split('-')
        return 'FuriOS ' + ' '.join(words)

    if partition_name.startswith('furios-'):
        name = partition_name.replace('furios-', '')
        words = name.split('-')
        return 'FuriOS ' + ' '.join(words)

    words = partition_name.split('-')
    return ' '.join(word.capitalize() for word in words)

def list_partitions():
    """
    List partitions in the /dev/droidian directory.

    Returns:
        list: List of partition names
    """
    droidian_path = Path("/dev/droidian")
    if not droidian_path.exists():
        return []

    return [p.name for p in droidian_path.iterdir()
            if p.name not in ['droidian-persistent', 'droidian-reserved']]

def write_partitions_file(partitions, password):
    """
    Write partitions to /furios_persist/bootman/partitions file.

    Args:
        partitions (list): List of partition names
        password (str): sudo password

    Returns:
        tuple: (success_boolean, message)
    """
    try:
        content = ''
        for partition in partitions:
            display_name = process_partition_name(partition)
            content += f"{partition}:{display_name}\n"

        cmd = ['sudo', '-S', 'tee', '/furios_persist/bootman/partitions']
        process = subprocess.Popen(cmd, stdin=subprocess.PIPE, text=True)
        process.communicate(input=content, timeout=2)

        if process.returncode != 0:
            return False, "Failed to write partitions file"

        subprocess.run(['sync'], check=True)
        return True, "Partitions file updated successfully"

    except subprocess.TimeoutExpired:
        process.kill()
        return False, "Timeout while writing partitions file"
    except Exception as e:
        return False, f"Error writing partitions file: {str(e)}"

def create_install_commands(password, name, size):
    """
    Create commands for creating a new partition.

    Args:
        password (str): sudo password
        name (str): Name of the new partition
        size (str): Size of the new partition in GB

    Returns:
        tuple: (success_boolean, message)
    """
    try:
        partition_name = name.replace(" ", "-").lower()

        # Check current root filesystem size
        cmd = f'echo {password} | sudo -S lvdisplay /dev/droidian/droidian-rootfs'
        result = subprocess.run(cmd, shell=True, text=True, capture_output=True)
        if result.returncode != 0:
            return False, "Failed to get current partition size"

        current_size = None
        for line in result.stdout.splitlines():
            if "LV Size" in line:
                current_size = float(line.split()[2])
                break

        if current_size is None:
            return False, "Could not determine current partition size"

        # Calculate new sizes
        new_size = current_size - float(size)

        # Convert GB to MB for all commands
        new_size_mb = int(new_size * 1024)
        size_mb = int(float(size) * 1024)

        # Prepare commands
        commands = [
            "e2fsck -p -y -f /dev/droidian/droidian-rootfs",
            f"resize2fs /dev/droidian/droidian-rootfs {new_size_mb}M",
            f"lvm lvreduce -L -{size_mb}M -r /dev/droidian/droidian-rootfs",
            f"lvm lvcreate -L {size_mb}M -n {partition_name} droidian"
        ]

        # Write commands to file
        content = "\n".join(commands) + "\n"
        cmd = ['sudo', '-S', 'tee', '/furios_persist/bootman/commands']
        process = subprocess.Popen(cmd, stdin=subprocess.PIPE, text=True)
        process.communicate(input=content, timeout=2)

        if process.returncode != 0:
            return False, "Failed to create commands file"

        # Update wip-partitions file
        wip_content = f"{partition_name}:{name}\n"
        cmd = ['sudo', '-S', 'tee', '-a', '/furios_persist/bootman/wip-partitions']
        process = subprocess.Popen(cmd, stdin=subprocess.PIPE, text=True)
        process.communicate(input=wip_content, timeout=2)

        if process.returncode != 0:
            return False, "Failed to update wip-partitions file"

        return True, "Commands and partition info created successfully"
    except subprocess.TimeoutExpired:
        return False, "Timeout while creating commands"
    except Exception as e:
        return False, f"Error creating commands: {str(e)}"

def read_partitions_file(partitions_file):
    """
    Read partitions from the file.

    Args:
        partitions_file (Path): Path to the partitions file

    Returns:
        list: List of (partition, name) tuples
    """
    try:
        with open(partitions_file, 'r') as f:
            content = f.read().strip()
            return [
                line.strip().split(':')
                for line in content.split('\n')
                if ':' in line
            ]
    except Exception as e:
        print(f"Error reading partitions: {str(e)}")
        return []

def delete_install_commands(password, partition_name):
    """
    Create commands for deleting a partition and adding its space back to rootfs.

    Args:
        password (str): sudo password
        partition_name (str): Name of the partition to delete

    Returns:
        tuple: (success_boolean, message)
    """
    try:
        # Get size of partition to be deleted
        cmd = f'echo {password} | sudo -S lvdisplay /dev/droidian/{partition_name}'
        result = subprocess.run(cmd, shell=True, text=True, capture_output=True)
        if result.returncode != 0:
            return False, "Failed to get partition size"

        size = None
        for line in result.stdout.splitlines():
            if "LV Size" in line:
                size = float(line.split()[2])
                unit = line.split()[3]
                # Convert to MB if in GB
                if unit.lower() == 'gib':
                    size = size * 1024
                break
        if size is None:
            return False, "Could not determine partition size"

        # Create commands to remove partition and extend rootfs
        commands = [
            f"lvm lvremove -f /dev/droidian/{partition_name}",
            f"lvm lvextend -L +{int(size)}M /dev/droidian/droidian-rootfs",
            "resize2fs /dev/droidian/droidian-rootfs"
        ]

        # Write commands to file
        content = "\n".join(commands) + "\n"
        cmd = ['sudo', '-S', 'tee', '/furios_persist/bootman/commands']
        process = subprocess.Popen(cmd, stdin=subprocess.PIPE, text=True)
        process.communicate(input=content, timeout=2)

        if process.returncode != 0:
            return False, "Failed to create commands file"

        # Remove entry from partitions file
        partitions = []
        with open('/furios_persist/bootman/partitions', 'r') as f:
            partitions = [line.strip() for line in f if partition_name not in line]

        content = "\n".join(partitions) + "\n"
        cmd = ['sudo', '-S', 'tee', '/furios_persist/bootman/partitions']
        process = subprocess.Popen(cmd, stdin=subprocess.PIPE, text=True)
        process.communicate(input=content, timeout=2)

        if process.returncode != 0:
            return False, "Failed to update partitions file"

        return True, "Delete commands created successfully"
    except subprocess.TimeoutExpired:
        return False, "Timeout while creating delete commands"
    except Exception as e:
        return False, f"Error creating delete commands: {str(e)}"
