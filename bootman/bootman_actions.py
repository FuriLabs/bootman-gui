# SPDX-License-Identifier: GPL-2.0
# Copyright (C) 2025 Bardia Moshiri <bardia@furilabs.com>

import subprocess
from pathlib import Path
import threading
import tempfile
import os

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
    if os.path.exists(f"/dev/droidian/{partition_name}"):
        success, output = run_helper("lvdisplay", f"/dev/droidian/{partition_name}")

        if success:
            for line in output.splitlines():
                if "LV Size" in line:
                    size = line.split()[2].replace(",", ".")
                    unit = line.split()[3]
                    return f"{size}{unit}"
    elif os.path.exists(partition_name):
        success, output = run_helper("blockdev", partition_name)
        if success:
            return f"{int(output) / (1024 * 1024 * 1024):.1f}GiB"
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
            size_str = line.split()[2].replace(',', '.')
            current_size = float(size_str)
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
        f"lvm lvcreate -L {size_mb}M -n {partition_name} droidian -y",
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

def create_external_install_commands(name, storage_location):
   """
   Create commands for creating a new partition on external storage.
   Args:
       name (str): Name of the new installation
       storage_location (str): Path to external storage device
   Returns:
       tuple: (success (bool), message (str))
   """
   commands = [
       f"mke2fs {storage_location}"
   ]

   success, _ = run_helper("write_commands", "\n".join(commands))
   if not success:
       return False, "Failed to write commands"

   success, _ = run_helper("write_wip", f"{storage_location}:{name}")
   if not success:
       return False, "Failed to write wip file"

   return True, "External partition creation queued successfully"

def create_delete_commands(partition_name):
    """Create commands for deleting a partition."""
    if os.path.exists(f"/dev/droidian/{partition_name}"):
        # Get partition size
        success, output = run_helper("lvdisplay", f"/dev/droidian/{partition_name}")
        if not success:
            return False, "Failed to get partition size"

        size = None
        for line in output.splitlines():
            if "LV Size" in line:
                size_str = line.split()[2].replace(",", ".")
                size = float(size_str)
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
            "e2fsck -fy /dev/droidian/droidian-rootfs",
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
    elif os.path.exists(partition_name):
        remove_partition_entry(partition_name)
        return True, f"Successfully deleted external storage install"
    return False, "Partition is not available"

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
        ),
        (
            "Ubuntu Touch",
            "Ubuntu Touch is a mobile version of Ubuntu",
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
        },
        "Ubuntu Touch": {
            "url": "https://filedump.furios.io/rootfs/rootfs-ubports.img",
            "md5_url": "https://filedump.furios.io/rootfs/rootfs-ubports.img.md5"
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
    if os.path.exists(f"/dev/droidian/{partition_name}"):
        partition_path = f"/dev/droidian/{partition_name}"
    elif os.path.exists(partition_name):
        partition_path = partition_name
    else:
        print("Partition path does not exist. something is seriously wrong")
        return

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
            f"umount -l {partition_path} || true",
            f"mount {partition_path} /mnt_newpart",
            f"mount \"{save_path}\" /mnt_rootfs",
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

def get_ignore_list():
    """
    Retrieves list of partition devices to ignore from config file.

    Returns:
        list: Device paths to ignore, empty if config not found
    """
    ignore_file = '/usr/lib/furios/device/bootman-ignore-partition'
    try:
        with open(ignore_file, 'r') as f:
            ignore_list = f.read().strip().split(':')
        return ignore_list
    except FileNotFoundError:
        print(f"Ignore file '{ignore_file}' not found. Skipping ignore list.")
        return []

def get_external_disks():
    """
    Gets list of external disk partitions, filtering special devices and ignores.

    Returns:
        list: Device paths of external disk partitions
    """
    cmd = "lsblk -l -n -o NAME,TYPE | grep ' part$'"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    ignore_list = get_ignore_list()

    valid_partitions = []
    for line in result.stdout.strip().split('\n'):
        if line.strip():
            dev_path = f"/dev/{line.split()[0]}"
            if os.path.exists(dev_path) and not any(dev_path.startswith(ignore) for ignore in ignore_list):
                valid_partitions.append(dev_path)

    return valid_partitions

def is_ubuntu_partition_available():
    if os.path.exists("/dev/droidian/ubuntu-userdata"):
        return True
    return False

def create_ubuntu_userdata_commands(partition_name):
    """
    Reduce a given partition to 4GB and create a new ubuntu-userdata partition
    with the remaining space.

    Args:
        partition_name: Name of the partition to resize

    Returns:
        tuple: (success, message)
    """
    # Get current partition size
    success, output = run_helper("lvdisplay", f"/dev/droidian/{partition_name}")
    if not success:
        return False, f"Failed to get current partition size for {partition_name}"

    current_size = None
    for line in output.splitlines():
        if "LV Size" in line:
            size_str = line.split()[2].replace(',', '.')
            current_size = float(size_str)
            break

    if current_size is None:
        return False, f"Could not determine current partition size for {partition_name}"

    # Calculate new sizes
    target_size = 4.0  # 4GB for the original partition
    if current_size <= target_size:
        return False, f"Partition {partition_name} is already 4GB or smaller"

    remaining_size = current_size - target_size
    target_size_mb = int(target_size * 1024)
    remaining_size_mb = int(remaining_size * 1024)

    # Save the owner partition name to a file
    owner_file = "/var/lib/furios-persist/bootman/ubuntu-userdata"

    # Create a temporary script
    temp_script = tempfile.NamedTemporaryFile(delete=False, mode='w', suffix='.sh')
    script_path = temp_script.name

    try:
        # Write commands to the script
        temp_script.write(f"#!/bin/bash\necho '{partition_name}' > {owner_file}\n")
        temp_script.close()

        # Make the script executable
        os.chmod(script_path, 0o755)

        # Execute with pkexec
        process = subprocess.Popen(
            ["pkexec", "/bin/bash", str(script_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True
        )

        # Wait for the process to complete
        stdout, _ = process.communicate()

        if process.returncode != 0:
            return False, f"Failed to save ubuntu-userdata owner: {stdout}"

    except Exception as e:
        return False, f"Error saving ubuntu-userdata owner: {str(e)}"
    finally:
        # Clean up the temporary script
        try:
            os.unlink(script_path)
        except:
            pass

    # Write the command file
    commands = [
        f"e2fsck -fy /dev/droidian/{partition_name}",
        f"resize2fs /dev/droidian/{partition_name} {target_size_mb}M",
        f"lvm lvreduce -L {target_size_mb}M -r /dev/droidian/{partition_name}",
        "lvm lvcreate -L {0}M -n ubuntu-userdata droidian -y".format(remaining_size_mb),
        "mke2fs /dev/droidian/ubuntu-userdata",
        "e2fsck -fy /dev/droidian/ubuntu-userdata"
    ]

    success, _ = run_helper("write_commands", "\n".join(commands))
    if not success:
        return False, "Failed to write commands"

    # Write the wip file
    success, _ = run_helper("write_wip", "ubuntu-userdata:Ubuntu Userdata")
    if not success:
        return False, "Failed to write wip file"

    return True, "Ubuntu UserData partition creation queued successfully"

def create_delete_ubuntu_commands(partition_name):
    """Create commands for deleting an Ubuntu partition and its userdata partition."""
    # Check if the main partition exists
    if not os.path.exists(f"/dev/droidian/{partition_name}"):
        return False, "Ubuntu partition is not available"

    # Check if the ubuntu-userdata partition exists
    if not os.path.exists("/dev/droidian/ubuntu-userdata"):
        return False, "Ubuntu userdata partition is not available"

    # Get main partition size
    success, output = run_helper("lvdisplay", f"/dev/droidian/{partition_name}")
    if not success:
        return False, "Failed to get main partition size"

    main_size = None
    for line in output.splitlines():
        if "LV Size" in line:
            size_str = line.split()[2].replace(",", ".")
            main_size = float(size_str)
            unit = line.split()[3]
            if unit.lower() == 'gib':
                main_size = main_size * 1024
            break

    if main_size is None:
        return False, "Could not determine main partition size"

    # Get userdata partition size
    success, output = run_helper("lvdisplay", "/dev/droidian/ubuntu-userdata")
    if not success:
        return False, "Failed to get userdata partition size"

    userdata_size = None
    for line in output.splitlines():
        if "LV Size" in line:
            size_str = line.split()[2].replace(",", ".")
            userdata_size = float(size_str)
            unit = line.split()[3]
            if unit.lower() == 'gib':
                userdata_size = userdata_size * 1024
            break

    if userdata_size is None:
        return False, "Could not determine userdata partition size"

    # Total size to reclaim
    total_size = int(main_size) + int(userdata_size)

    # Remove WIP
    success, output = run_helper("remove_wip")
    if not success:
        return False, "Failed to remove wip"

    # Write the command file
    commands = [
        # Remove both partitions
        f"lvm lvremove -f /dev/droidian/{partition_name}",
        "lvm lvremove -f /dev/droidian/ubuntu-userdata",
        # Extend the root filesystem with the total reclaimed space
        f"lvm lvextend -L +{total_size}M /dev/droidian/droidian-rootfs",
        # Check and resize the root filesystem
        "e2fsck -fy /dev/droidian/droidian-rootfs",
        "resize2fs /dev/droidian/droidian-rootfs"
    ]

    success, _ = run_helper("write_commands", "\n".join(commands))
    if not success:
        return False, "Failed to write commands"

    # Update partitions file
    success, output = run_helper("cat", "/var/lib/furios-persist/bootman/partitions")
    if success:
        partitions = [line.strip() for line in output.splitlines()
                      if partition_name not in line and "ubuntu-userdata" not in line]
        content = "\n".join(partitions)
        success, _ = run_helper("write_partitions", content)
        if not success:
            return False, "Failed to update partitions file"

    # Remove both partition entries
    remove_partition_entry(partition_name)
    remove_partition_entry("ubuntu-userdata")

    return True, "Deletion of Ubuntu and userdata partitions queued successfully"

def get_ubuntu_userdata_owner():
    """
    Get the partition name that owns the ubuntu-userdata partition.

    Returns:
        str or None: The partition name if found, None otherwise
    """
    owner_file = "/var/lib/furios-persist/bootman/ubuntu-userdata"

    # Check if the file exists
    if not os.path.exists(owner_file):
        return None

    # Read the file content
    try:
        with open(owner_file, 'r') as f:
            owner = f.read().strip()
            return owner if owner else None
    except Exception:
        return None
