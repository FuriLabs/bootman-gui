# SPDX-License-Identifier: GPL-2.0
# Copyright (C) 2025 Bardia Moshiri <bardia@furilabs.com>

import subprocess
from pathlib import Path
import threading

_command_lock = threading.Lock()
HELPER_PATH = "/usr/libexec/bootman-helper"

def run_helper(*args):
    """
    Run the bootman helper script with the given arguments.

    Args:
        *args: Arguments to pass to the helper script

    Returns:
        tuple: (success_boolean, message)
    """
    global _command_lock

    with _command_lock:  # Ensure only one privileged operation runs at a time
        try:
            result = subprocess.run(
                ['pkexec', HELPER_PATH, *map(str, args)],
                capture_output=True,
                text=True
            )

            if result.returncode != 0:
                return False, f"Command execution failed: {result.stderr}"
            return True, result.stdout
        except Exception as e:
            return False, f"Error executing command: {str(e)}"

def mount_partition():
    """Mount the FuriOS persist partition."""
    return run_helper("mount")

def get_partition_size(partition_name):
    """Get the size of a specific LVM partition."""
    success, output = run_helper("lvdisplay", f"/dev/droidian/{partition_name}")

    if success:
        for line in output.splitlines():
            if "LV Size" in line:
                size = line.split()[2]
                unit = line.split()[3]
                return f"{size}{unit}"
    return "Unknown"

def write_partitions_file(partitions):
    """Write partitions to //var/lib/furios-persist/bootman/partitions file."""
    content = ''
    for partition in partitions:
        display_name = process_partition_name(partition)
        content += f"{partition}:{display_name}\n"

    return run_helper("write_partitions", content)

def create_install_commands(name, size):
    """Create commands for creating a new partition."""
    partition_name = name.replace(" ", "-").lower()

    # Get current root filesystem size
    success, output = run_helper("lvdisplay", "/dev/droidian/droidian-rootfs")
    if not success:
        return False, "Failed to get current partition size"

    current_size = None
    for line in output.splitlines():
        if "LV Size" in line:
            current_size = float(line.split()[2])
            break

    if current_size is None:
        return False, "Could not determine current partition size"

    # Calculate new sizes
    new_size = current_size - float(size)
    new_size_mb = int(new_size * 1024)
    size_mb = int(float(size) * 1024)

    # Write the command file
    commands = [
        "e2fsck -fy /dev/droidian/droidian-rootfs",
        f"resize2fs /dev/droidian/droidian-rootfs {new_size_mb}M",
        f"lvm lvreduce -L -{size_mb}M -r /dev/droidian/droidian-rootfs",
        f"lvm lvcreate -L {size_mb}M -n {partition_name} droidian",
        f"mke2fs /dev/droidian/{partition_name}",
        f"e2fsck -fy /dev/droidian/{partition_name}"
    ]
    success, _ = run_helper("write_commands", "\n".join(commands))
    if not success:
        return False, "Failed to write commands"

    # Write the wip file
    success, _ = run_helper("write_wip", f"{partition_name}:{name}")
    if not success:
        return False, "Failed to write wip file"

    return True, "Partition creation queued successfully"

def delete_install_commands(partition_name):
    """Create commands for deleting a partition."""
    # Get partition size
    success, output = run_helper("lvdisplay", f"/dev/droidian/{partition_name}")
    if not success:
        return False, "Failed to get partition size"

    size = None
    for line in output.splitlines():
        if "LV Size" in line:
            size = float(line.split()[2])
            unit = line.split()[3]
            if unit.lower() == 'gib':
                size = size * 1024
            break

    if size is None:
        return False, "Could not determine partition size"

    # Remove WIP
    success, output = run_helper("remove_wip")
    if not success:
        return False, "Failed to remove wip"

    # Write the command file
    commands = [
        f"lvm lvremove -f /dev/droidian/{partition_name}",
        f"lvm lvextend -L +{int(size)}M /dev/droidian/droidian-rootfs",
        "resize2fs /dev/droidian/droidian-rootfs"
    ]
    success, _ = run_helper("write_commands", "\n".join(commands))
    if not success:
        return False, "Failed to write commands"

    # Update partitions file
    success, output = run_helper("cat", "/var/lib/furios-persist/bootman/partitions")
    if success:
        partitions = [line.strip() for line in output.splitlines() if partition_name not in line]
        content = "\n".join(partitions)
        success, _ = run_helper("write_partitions", content)
        if not success:
            return False, "Failed to update partitions file"

    remove_partition_entry(partition_name)
    return True, "Deletion queued successfully"

def remove_partition_entry(partition_name):
    return run_helper("remove_entry", partition_name)

def is_mounted(mount_point):
    """Check if a mount point is currently mounted."""
    try:
        return Path('/proc/mounts').read_text().find(mount_point) != -1
    except Exception:
        return False

def is_partition_mounted(partition_name):
    """Check if a specific partition is currently mounted."""
    try:
        return Path('/proc/mounts').read_text().find(f"/dev/droidian/{partition_name}") != -1
    except Exception:
        return False

def process_partition_name(partition_name):
    """Convert a partition name to a more readable format."""
    name = partition_name.replace('droidian-', '').replace('furios-', '')
    words = name.split('-')
    return ' '.join(word.capitalize() for word in words)

def list_partitions():
    """List all available partitions."""
    try:
        droidian_path = Path("/dev/droidian")
        if not droidian_path.exists():
            return []

        excluded = ['droidian-persistent', 'droidian-reserved']
        return [p.name for p in droidian_path.iterdir()
                if p.exists() and p.name not in excluded]
    except Exception:
        return []

def read_partitions_file(partitions_file):
    """Read and parse the partitions file."""
    try:
        content = Path(partitions_file).read_text().strip()
        return [line.strip().split(':')
                for line in content.split('\n')
                if ':' in line]
    except Exception:
        return []

def get_queued_partition():
    """
    Check for any queued partition operations.

    Returns:
        tuple: (operation, partition_name, display_name) where:
               operation is either 'install' or 'delete'
               partition_name is the name of the partition
               display_name is the friendly name for display
        None: if no queue exists
    """
    try:
        wip_file = Path("/var/lib/furios-persist/bootman/wip-partitions")
        commands_file = Path("/var/lib/furios-persist/bootman/commands")

        # Check if commands file exists
        if not commands_file.exists():
            return None

        commands_content = commands_file.read_text().strip()
        if not commands_content:
            return None

        # Check if it's an installation (both files exist)
        if wip_file.exists():
            wip_content = wip_file.read_text().strip()
            if wip_content and ':' in wip_content:
                partition_name, display_name = wip_content.split(':', 1)
                return ('install', partition_name.strip(), display_name.strip())

        # If no wip file but commands exist, check for deletion
        for line in commands_content.split('\n'):
            if 'lvremove' in line:
                # Extract partition name from command like "lvm lvremove -f /dev/droidian/partition-name"
                partition_name = line.split('/')[-1].strip()
                display_name = partition_name.replace('-', ' ')
                return ('delete', partition_name, display_name)

        return None
    except Exception:
        return None

def get_supported_operating_systems():
    """
    Get list of supported operating systems.

    Returns:
        list: List of tuples containing (name, description, icon_name)
    """
    return [
        (
            "FuriOS",
            "FuriOS is a Linux OS for mobile devices from FuriLabs",
            "computer-symbolic"
        )
    ]

def get_os_download_info(os_name):
    """
    Get the download information for a specific operating system.

    Args:
        os_name (str): Name of the operating system

    Returns:
        tuple: (url, md5_url) or (None, None) if not found
        url is the OS image URL
        md5_url is the MD5 checksum URL (can be None if no MD5 verification needed)
    """
    os_map = {
        "FuriOS": {
            "url": "https://filedump.furios.io/rootfs/rootfs.img",
            "md5_url": "https://filedump.furios.io/rootfs/rootfs.img.md5"
        }
    }

    if os_name in os_map:
        return os_map[os_name]["url"], os_map[os_name].get("md5_url")
    return None, None

def run_install_commands(partition_name, save_path, output_callback=None):
    """
    Create and execute installation commands with elevated privileges.

    Args:
        partition_name (str): Target partition name
        save_path (Path): Path to OS image
        output_callback (callable): Optional callback for output lines

    Returns:
        tuple: (success_boolean, message)
    """
    # Create temporary script
    script_path = Path("/tmp/bootman_install.sh")

    try:
        # Create script content with proper command sequence
        commands = [
            "#!/bin/bash",
            "set -e",  # Exit on any error
            "set -x",  # Echo commands as they are executed
            "",
            "# Create mount points",
            "mkdir -p /mnt_newpart",
            "mkdir -p /mnt_rootfs",
            "",
            f"# Mount partitions",
            f"mount /dev/droidian/{partition_name} /mnt_newpart",
            f"mount {save_path} /mnt_rootfs",
            "",
            "# Copy files",
            "rsync --archive -H -A -X --info=name2 /mnt_rootfs/* /mnt_newpart/ || true",
            "rsync --archive -H -A -X --info=name2 /mnt_rootfs/.[^.]* /mnt_newpart/ || true",
            "",
            "# Cleanup",
            "umount -l /mnt_newpart",
            "umount -l /mnt_rootfs",
            "rm -rf /mnt_newpart",
            "rm -rf /mnt_rootfs"
        ]

        script_path.write_text("\n".join(commands))
        script_path.chmod(0o700)

        # Execute with pkexec
        process = subprocess.Popen(
            ["pkexec", "/bin/bash", str(script_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True
        )

        # Read output in real-time
        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            if line and output_callback:
                output_callback(line)

        # Get final return code
        return_code = process.wait()
        if return_code != 0:
            return False, f"Installation failed with code {return_code}"

        return True, "Installation completed successfully"
    except Exception as e:
        return False, f"Installation error: {str(e)}"
    finally:
        # Always clean up the script
        try:
            script_path.unlink(missing_ok=True)
        except Exception as e:
            print(f"Warning: Failed to remove temporary script: {e}")
