from os import system, environ, chdir, path
import sys
import json
from subprocess import run, PIPE


# Load configuration file
with open("config.json") as confFile:
    conf = json.load(confFile)


def validKey(name: str):
    if name in conf.keys() and len(conf[name]) > 0:
        return True
    else:
        return False


URL = "https://github.com/RfidResearchGroup/proxmark3.git"

if validKey("URL"):
    print("Using repo", URL, flush=True)
    URL = conf["URL"]

# Switch to the working directory
ref = environ["MATRIX_REF"]
refPath = "pm3-" + ref
chdir(environ["GITHUB_WORKSPACE"])
print("Cloning", refPath, flush=True)
system(
    "git -c advice.detachedHead=false"
    " clone " + URL + " --depth=1 -b " + ref + " " + refPath
)
if not path.exists("./" + refPath):  # Clone failed, try a full clone instead
    system("git clone " + URL + " " + refPath)
    chdir(refPath)
    system("git -c advice.detachedHead=false checkout " + ref)
else:
    chdir(refPath)

# Save commit SHA1
sha1 = run("git rev-parse HEAD", shell=True, stdout=PIPE).stdout
sha1 = sha1.decode("utf-8").strip()
print(sha1, flush=True)
# BUGFIX: mkdir creates ../artifacts/<ref>/, so the SHA1 marker must live
# inside the same directory. Previously it was written to
# ../artifacts/<sha1>.txt, which is inconsistent with the artifact layout
# used later (../artifacts/<ref>/<sha1>/...).
system(f"mkdir -p ../artifacts/{ref}")
system(f"touch ../artifacts/{ref}/{sha1}.txt")

standalone = environ["MATRIX_STANDALONE"]
modeName = standalone if len(standalone) != 0 else "empty"
print("Building firmware for standalone mode:", modeName, flush=True)
if standalone == "empty":
    standalone = ""

# Detect the platform sample version to decide whether PM3GENERIC must be
# remapped to PM3OTHER.
oldVersion = True
with open("Makefile.platform.sample", "r") as sample:
    for line in sample:
        if "PM3GENERIC" in line:
            oldVersion = False
            break

# Pre-compute the platform name
platform = conf.get("PLATFORM", "PM3GENERIC")
if oldVersion and platform == "PM3GENERIC":
    platform = "PM3OTHER"


def build_firmware(variant_name, extra_skip_options):
    """
    Build the firmware for the given variant.
    :param variant_name: Variant name, used for the output subdirectory,
                         e.g. "no_lf", "no_hf".
    :param extra_skip_options: Additional SKIP_* options for this variant.
    """
    print(f"\n===== Building variant: {variant_name} =====", flush=True)

    # Merge extraOptions from config with this variant's extra skip options,
    # de-duplicating entries.
    all_options = list(conf.get("extraOptions", []))
    for opt in extra_skip_options:
        if opt not in all_options:
            all_options.append(opt)

    # Generate Makefile.platform
    with open("Makefile.platform", "w+") as mp:
        mp.write("STANDALONE=" + standalone + "\n")
        mp.write("PLATFORM=" + platform + "\n")
        if validKey("PLATFORM_EXTRAS"):
            mp.write("PLATFORM_EXTRAS=" + conf["PLATFORM_EXTRAS"] + "\n")
        if validKey("PLATFORM_SIZE"):
            mp.write("PLATFORM_SIZE=" + conf["PLATFORM_SIZE"] + "\n")
        for option in all_options:
            mp.write(option + "=1\n")
        if validKey("extraLines"):
            for line in conf["extraLines"]:
                mp.write(line + "\n")

    # Clean and build
    system("make clean -j 1> /dev/null")
    exitCode = system("make -j bootrom fullimage recovery")

    # Check the build result
    checkPath = "./bootrom/obj/bootrom.elf"
    if not path.exists(checkPath):
        print(f"{checkPath} doesn't exist, Exiting...", flush=True)
        sys.exit(-1)
    elif exitCode != 0:
        print(f"Error occurs during build of {variant_name}: {exitCode}", flush=True)
        sys.exit(-1)

    # Create the per-variant output directory
    output_dir = f"../artifacts/{ref}/{sha1}/{variant_name}/"
    system(f"mkdir -p {output_dir}")

    # Collect the generated files
    system(f"mv bootrom/obj/bootrom.elf {output_dir}")
    system(f"mv armsrc/obj/fullimage.elf {output_dir}")
    system(f"mv recovery/proxmark3_recovery.bin {output_dir}")

    if conf.get("buildS19", False):
        system(f"mv bootrom/obj/bootrom.s19 {output_dir}")
        system(f"mv armsrc/obj/fullimage.s19 {output_dir}")

    # Move Makefile.platform so it is archived alongside the artifacts
    system(f"mv ./Makefile.platform {output_dir}")

    print(f"Variant {variant_name} built successfully. Output in {output_dir}", flush=True)


# ---------------------------------------------------------------------------
# SKIP options for the two variants.
#
# IMPORTANT:
#   - `extraOptions` in config.json should only contain COMMON options.
#   - Do NOT put HF- or LF-specific SKIPs there.
#   - All HF-specific SKIPs belong to `HF_SKIP_OPTIONS`.
#   - All LF-specific SKIPs belong to `LF_SKIP_OPTIONS`.
# ---------------------------------------------------------------------------

# LF modules to skip when building an HF-only firmware (`no_lf`).
LF_SKIP_OPTIONS = [
    "SKIP_LF",          # If supported by the current codebase, otherwise harmless.
    "SKIP_HITAG",
    "SKIP_EM4x50",
    "SKIP_EM4X70",
    "SKIP_ZX8211",
]

# HF modules to skip when building an LF-only firmware (`no_hf`).
HF_SKIP_OPTIONS = [
    "SKIP_ISO14443a",
    "SKIP_ISO14443b",
    "SKIP_ISO15693",
    "SKIP_FELICA",
    "SKIP_ICLASS",
    "SKIP_LEGICRF",
    "SKIP_HFSNIFF",
    "SKIP_HFPLOT",
    "SKIP_SEOS",
]

# Build both variants in order.
#   no_lf -> HF-only firmware (skip LF modules)
#   no_hf -> LF-only firmware (skip HF modules)
build_firmware("no_lf", LF_SKIP_OPTIONS)
build_firmware("no_hf", HF_SKIP_OPTIONS)

print("\nAll variants built successfully.", flush=True)
