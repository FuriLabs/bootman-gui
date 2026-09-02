# SPDX-License-Identifier: GPL-2.0
# Copyright (C) 2026 Bardia Moshiri <bardia@furilabs.com>

import os
import shlex
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Tuple
from urllib3 import request

from bootman.models import OperatingSystem, OSDownloadInfo, OSRelease, OSTypes

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

def is_encrypted():
    """
    Check if the device is encrypted by looking for encrypted mapper devices.

    Returns:
        bool: True if device is encrypted, False otherwise
    """
    try:
        droidian_encrypted = Path("/dev/mapper/droidian_encrypted")
        furios_encrypted = Path("/dev/mapper/furios_encrypted")

        return droidian_encrypted.exists() or furios_encrypted.exists()
    except Exception:
        return False

def mount_partition():
    """Mount the FuriOS persist partition."""
    return run_helper("mount")

def get_lvm_type():
    """Get the LVM type by checking which volume group exists."""
    if os.path.exists("/dev/furios"):
        return "furios"
    elif os.path.exists("/dev/droidian"):
        return "droidian"
    else:
        return ""

def get_codename():
    """Reads the device codename from /usr/lib/furios/device/codename"""
    try:
        with open('/usr/lib/furios/device/codename', 'r') as file:
            content = file.read().strip()
            return content
    except FileNotFoundError:
        return ""
    except Exception:
        return ""

def get_partition_size(partition_name):
    """Get the size of a specific LVM partition."""
    lvm_type = get_lvm_type()

    if lvm_type and os.path.exists(f"/dev/{lvm_type}/{partition_name}"):
        success, output = run_helper("lvdisplay", f"/dev/{lvm_type}/{partition_name}")
        if success:
            for line in output.splitlines():
                if "LV Size" in line:
                    size_str = line.split()[2].replace(',', '.').replace('<', '')
                    unit = line.split()[3]
                    return f"{size_str}{unit}"
    elif os.path.exists(partition_name):
        success, output = run_helper("blockdev", partition_name)
        if success:
            return f"{int(output) / (1024 * 1024 * 1024):.1f}GiB"
    return "Unknown"

def write_partitions_file(partitions):
    """Write partitions to /var/lib/furios-persist/bootman/partitions file."""
    content = ''
    for partition in partitions:
        display_name = process_partition_name(partition)
        content += f"{partition}:{display_name}\n"

    return run_helper("write_partitions", content)

def create_install_commands(name, size):
    """Create commands for creating a new partition."""
    partition_name = name.replace(" ", "-").lower()
    lvm_type = get_lvm_type()

    if not lvm_type:
        return False, "No LVM volume group found"

    # Get current root filesystem size
    success, output = run_helper("lvdisplay", f"/dev/{lvm_type}/{lvm_type}-rootfs")
    if not success:
        return False, "Failed to get current partition size"

    current_size = None
    for line in output.splitlines():
        if "LV Size" in line:
            size_str = line.split()[2].replace(',', '.').replace('<', '')
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
        f"e2fsck -fy /dev/{lvm_type}/{lvm_type}-rootfs",
        f"resize2fs /dev/{lvm_type}/{lvm_type}-rootfs {new_size_mb}M",
        f"lvm lvreduce -L -{size_mb}M -r /dev/{lvm_type}/{lvm_type}-rootfs",
        f"lvm lvcreate -L {size_mb}M -n {partition_name} {lvm_type} -y",
        f"mke2fs -t ext4 -b 4096 /dev/{lvm_type}/{partition_name}",
        f"e2fsck -fy /dev/{lvm_type}/{partition_name}"
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
       f"mke2fs -t ext4 -b 4096 {storage_location}"
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
    lvm_type = get_lvm_type()

    if lvm_type and os.path.exists(f"/dev/{lvm_type}/{partition_name}"):
        # Get partition size
        success, output = run_helper("lvdisplay", f"/dev/{lvm_type}/{partition_name}")
        if not success:
            return False, "Failed to get partition size"

        size = None
        for line in output.splitlines():
            if "LV Size" in line:
                size_str = line.split()[2].replace(',', '.').replace('<', '')
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
            f"lvm lvremove -f /dev/{lvm_type}/{partition_name}",
            f"lvm lvextend -L +{int(size)}M /dev/{lvm_type}/{lvm_type}-rootfs",
            f"e2fsck -fy /dev/{lvm_type}/{lvm_type}-rootfs",
            f"resize2fs /dev/{lvm_type}/{lvm_type}-rootfs"
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
        return True, "Successfully deleted external storage install"
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
        lvm_type = get_lvm_type()
        if lvm_type:
            return Path('/proc/mounts').read_text().find(f"/dev/{lvm_type}/{partition_name}") != -1
        return False
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
        lvm_type = get_lvm_type()
        if not lvm_type:
            return []

        lvm_path = Path(f"/dev/{lvm_type}")
        if not lvm_path.exists():
            return []

        excluded = [f'{lvm_type}-persistent', f'{lvm_type}-reserved']
        return [p.name for p in lvm_path.iterdir()
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
                # Extract partition name from command like "lvm lvremove -f /dev/{lvm_type}/partition-name"
                partition_name = line.split('/')[-1].strip()
                display_name = partition_name.replace('-', ' ')
                return ('delete', partition_name, display_name)

        return None
    except Exception:
        return None


def _get_jenkins_download_ws_info(
    os_type: OSTypes,
    file: Path,
    release_name: str,
    job_name: str,
    codename: str,
    artifact_extension: str,
) -> OSDownloadInfo:
    download_info = OSDownloadInfo(os_type=os_type, file=file)
    try:
        # Get latest build from jenkins
        jenkins_latest = request(
            "GET",
            f"https://jenkins.furios.io/job/{job_name}/lastSuccessfulBuild/api/json",
        ).json()
        latest_rev = jenkins_latest["number"]

        # WS doesnt have api/json to enumerate the artifacts so just hard code based on os_type
        if os_type == OSTypes.FuriOS:
            prefix = "rootfs"
        elif os_type == OSTypes.UbuntuTouch:
            prefix = "ubports"
        else:
            raise Exception(f"Unsupported os_type: {os_type.name} for workspace")

        download_info.url = f"https://jenkins.furios.io/job/{job_name}/ws/{prefix}-{codename}-{latest_rev}{artifact_extension}"
        download_info.md5_url = f"https://jenkins.furios.io/job/{job_name}/ws/{prefix}-{codename}-{latest_rev}{artifact_extension}.md5"
    except Exception as e:
        print(
            f"Failed to get jenkins build for {os_type.name} {release_name} {codename}: {e}"
        )

    return download_info


def _get_jenkins_download_build_info(
    os_type: OSTypes,
    file: Path,
    release_name: str,
    job_name: str,
    codename: str,
    artifact_extension: str,
) -> OSDownloadInfo:
    download_info = OSDownloadInfo(os_type=os_type, file=file)
    try:
        # Get latest build from jenkins
        jenkins_latest = request(
            "GET",
            f"https://jenkins.furios.io/job/{job_name}/lastSuccessfulBuild/api/json",
        ).json()
        latest_rev = jenkins_latest["number"]
        artifacts = jenkins_latest["artifacts"]

        image_path: Path | None = None
        md5_path: Path | None = None
        for artifact in artifacts:
            relative = Path(artifact["relativePath"])
            if relative.suffix == artifact_extension:
                image_path = relative
            if relative.suffix == ".md5":
                md5_path = relative

        if image_path:
            download_info.url = f"https://jenkins.furios.io/job/{job_name}/{latest_rev}/artifact/{image_path.as_posix()}"

        if md5_path:
            download_info.md5_url = f"https://jenkins.furios.io/job/{job_name}/{latest_rev}/artifact/{md5_path.as_posix()}"
    except Exception as e:
        print(
            f"Failed to get jenkins build for {os_type.name} {release_name} {codename}: {e}"
        )

    return download_info


def get_supported_operating_systems(dir: Path) -> Tuple[OperatingSystem, ...]:
    """Build the supported OS tree with the latest available download URLs."""
    codename = get_codename()

    furios_stable = _get_jenkins_download_ws_info(
        os_type=OSTypes.FuriOS,
        file=dir / f"furios_stable_{codename}.img",
        release_name="stable",
        job_name=f"furios%20production%20{codename}",
        codename=codename,
        artifact_extension=".img",
    )
    furios_nightly = _get_jenkins_download_ws_info(
        os_type=OSTypes.FuriOS,
        file=dir / f"furios_nightly_{codename}.img",
        release_name="nightly",
        job_name=f"furios%20nightly%20{codename}",
        codename=codename,
        artifact_extension=".img",
    )
    ubuntu_touch_stable = _get_jenkins_download_ws_info(
        os_type=OSTypes.UbuntuTouch,
        file=dir / f"ubuntu_touch_stable_{codename}.img",
        release_name="stable",
        job_name=f"ubuntu%20touch%20{codename}",
        codename=codename,
        artifact_extension=".img",
    )

    # Sailfish only supports krypton
    if codename == "krypton":
        sailfish_stable = _get_jenkins_download_build_info(
                os_type=OSTypes.Sailfish,
                file=dir / f"sailfish_stable_{codename}.tar.bz2",
                release_name="stable",
                job_name=f"sailfish-release-halium-{codename}",
                codename=codename,
                artifact_extension=".bz2",
            )
    else:
       sailfish_stable = OSDownloadInfo(os_type=OSTypes.Sailfish, file=dir / f"sailfish_stable_{codename}.tar.bz2")

    furios_os = OperatingSystem(
            name="FuriOS",
            description="FuriOS is a Debian based system made by FuriLabs",
            options=(
                OSRelease(
                    name="Stable",
                    description="Production release recommended for everyday use",
                    download=furios_stable,
                ),
                OSRelease(
                    name="Nightly",
                    description="Development release with the latest changes",
                    download=furios_nightly,
                ),
            ),
        )

    ubuntu_touch_os = OperatingSystem(
        name="Ubuntu Touch",
        description="Ubuntu Touch is a mobile version of Ubuntu",
        options=(
            OSRelease(
                name="Stable",
                description="Production release recommended for everyday use",
                download=ubuntu_touch_stable,
            ),
        ),
    )

    sailfish_os = OperatingSystem(
        name="Sailfish",
        description="SailfishOS community port of Jollas Mobile OS",
        options=(
            OSRelease(
                name="Stable",
                description="Production release recommended for everyday use",
                download=sailfish_stable,
            ),
        ),
    )

    return (
        furios_os,
        ubuntu_touch_os,
        sailfish_os,
    )


def run_install_commands(partition_name, download_info: OSDownloadInfo, output_callback=None):
    """
    Create and execute installation commands with elevated privileges.
    Args:
        partition_name (str): Target partition name
        save_path (Path): Path to OS image
        output_callback (callable): Optional callback for output lines
    Returns:
        tuple: (success_boolean, message)
    """
    lvm_type = get_lvm_type()

    if lvm_type and os.path.exists(f"/dev/{lvm_type}/{partition_name}"):
        partition_path = f"/dev/{lvm_type}/{partition_name}"
    elif os.path.exists(partition_name):
        partition_path = partition_name
    else:
        print("Partition path does not exist. something is seriously wrong")
        return

    # Create temporary script
    script_path = Path("/tmp/bootman_install.sh")

    try:
        image_path = shlex.quote(str(download_info.file))
        mount_save: list[str] | None = None
        if download_info.file.suffix == ".img":
            mount_save = [
                f"mount -o ro {image_path} /mnt_rootfs",
                "",
                "# Copy files",
                "rsync --archive -H -A -X --info=name2 /mnt_rootfs/* /mnt_newpart/ || true",
                "rsync --archive -H -A -X --info=name2 /mnt_rootfs/.[^.]* /mnt_newpart/ || true",
                "",
                "# Cleanup",
                "umount -l /mnt_rootfs",
                "rm -rf /mnt_rootfs",
            ]
        elif download_info.file.suffix == ".bz2":
            if download_info.os_type == OSTypes.Sailfish:
                mount_save = [
                    f"tar --numeric-owner --strip-components=2 -xvf {image_path} -C /mnt_newpart",
                    "",
                    "# Cleanup",
                ]

        if not mount_save:
            raise Exception(f"{download_info.file.suffix} for {download_info.os_type.name} systems are not supported")

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
            "# Mount partitions",
            f"umount -l {partition_path} || true",
            f"mkfs.ext4 -F {partition_path}",
            f"mount -t ext4 {partition_path} /mnt_newpart"
        ] + mount_save + [
            "umount -l /mnt_newpart",
            "rm -rf /mnt_newpart",
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
    lvm_type = get_lvm_type()
    if os.path.exists(f"/dev/{lvm_type}/ubuntu-userdata"):
        return True
    return False

def create_ubuntu_userdata_commands(partition_name, output_callback = None):
    """
    Reduce a given partition to 5GB and create a new ubuntu-userdata partition
    with the remaining space.
    Args:
        partition_name: Name of the partition to resize
        output_callback (callable): Optional line-callback
    Returns:
        tuple: (success, message)
    """
    lvm_type = get_lvm_type()

    if not lvm_type:
        return False, "No LVM volume group found"

    # Get current partition size
    success, output = run_helper("lvdisplay", f"/dev/{lvm_type}/{partition_name}")
    if not success:
        return False, f"Failed to get current partition size for {partition_name}"

    current_size = None
    for line in output.splitlines():
        if "LV Size" in line:
            size_str = line.split()[2].replace(',', '.').replace('<', '')
            current_size = float(size_str)
            break

    if current_size is None:
        return False, f"Could not determine current partition size for {partition_name}"

    # Calculate new sizes
    target_size = 5.0  # 5GB for the original partition
    if current_size <= target_size:
        return False, f"Partition {partition_name} is already 5GB or smaller"

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
        "set -e",  # Exit on any error
        "set -x",  # Echo commands as they are executed
        "",
        f"umount -l /dev/{lvm_type}/{partition_name} || true",
        f"umount -l /dev/{lvm_type}/ubuntu-userdata || true",
        f"e2fsck -fy /dev/{lvm_type}/{partition_name}",
        f"resize2fs /dev/{lvm_type}/{partition_name} {target_size_mb}M",
        f"lvm lvreduce -L {target_size_mb}M -r /dev/{lvm_type}/{partition_name} -y",
        f"lvm lvcreate -L {remaining_size_mb}M -n ubuntu-userdata {lvm_type} -y",
        f"mke2fs -t ext4 -b 4096 /dev/{lvm_type}/ubuntu-userdata",
        f"e2fsck -fy /dev/{lvm_type}/ubuntu-userdata"
    ]

    # Build a temporary script and run with pkexec, streaming output
    script_path = Path("/tmp/bootman_userdata_split.sh")
    try:
        script_lines = ["#!/bin/bash"] + commands
        script_path.write_text("\n".join(script_lines))
        script_path.chmod(0o700)

        process = subprocess.Popen(
            ["pkexec", "/bin/bash", str(script_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True
        )

        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            if line and output_callback:
                output_callback(line)

        rc = process.wait()
        if rc != 0:
            return False, f"Ubuntu userdata creation failed with code {rc}"
        return True, "Ubuntu UserData partition created successfully"
    except Exception as e:
        return False, f"Immediate userdata creation error: {str(e)}"
    finally:
        try:
            script_path.unlink(missing_ok=True)
        except Exception:
            pass

def create_delete_ubuntu_commands(partition_name):
    """Create commands for deleting an Ubuntu partition and its userdata partition."""
    lvm_type = get_lvm_type()

    if not lvm_type:
        return False, "No LVM volume group found"

    # Check if the main partition exists
    if not os.path.exists(f"/dev/{lvm_type}/{partition_name}"):
        return False, "Ubuntu partition is not available"

    # Get main partition size
    success, output = run_helper("lvdisplay", f"/dev/{lvm_type}/{partition_name}")
    if not success:
        return False, "Failed to get main partition size"

    main_size = None
    for line in output.splitlines():
        if "LV Size" in line:
            size_str = line.split()[2].replace(',', '.').replace('<', '')
            main_size = float(size_str)
            unit = line.split()[3]
            if unit.lower() == 'gib':
                main_size = main_size * 1024
            break

    if main_size is None:
        return False, "Could not determine main partition size"

    # Get userdata partition size
    success, output = run_helper("lvdisplay", f"/dev/{lvm_type}/ubuntu-userdata")
    userdata_size = None
    if success:
        for line in output.splitlines():
            if "LV Size" in line:
                size_str = line.split()[2].replace(',', '.').replace('<', '')
                userdata_size = float(size_str)
                unit = line.split()[3]
                if unit.lower() == 'gib':
                    userdata_size = userdata_size * 1024
                break

        if userdata_size is None:
            return False, "Could not determine userdata partition size"

    # Total size to reclaim
    total_size = int(main_size) + int(userdata_size or 0)

    # Remove WIP
    success, output = run_helper("remove_wip")
    if not success:
        return False, "Failed to remove wip"

    # Write the command file
    commands = [
        # Remove both partitions
        f"lvm lvremove -f /dev/{lvm_type}/{partition_name}",
        f"lvm lvremove -f /dev/{lvm_type}/ubuntu-userdata" if userdata_size else "echo 'No userdata partition to remove'",
        # Extend the root filesystem with the total reclaimed space
        f"lvm lvextend -L +{total_size}M /dev/{lvm_type}/{lvm_type}-rootfs",
        # Check and resize the root filesystem
        f"e2fsck -fy /dev/{lvm_type}/{lvm_type}-rootfs",
        f"resize2fs /dev/{lvm_type}/{lvm_type}-rootfs"
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
    if userdata_size:
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
