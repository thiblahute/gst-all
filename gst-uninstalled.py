#!/usr/bin/env python3

import argparse
import json
import os
import platform
import re
import site
import shutil
import subprocess
import sys
import tempfile

from common import get_meson

SCRIPTDIR = os.path.abspath(os.path.dirname(__file__))
PREFIX_DIR = os.path.join(SCRIPTDIR, 'prefix')


def prepend_env_var(env, var, value):
    env[var] = os.pathsep + value + os.pathsep + env.get(var, "")
    env[var] = env[var].replace(os.pathsep + os.pathsep, os.pathsep).strip(os.pathsep)


def get_subprocess_env(options):
    env = os.environ.copy()

    env["CURRENT_GST"] = os.path.normpath(SCRIPTDIR)
    env["GST_VALIDATE_SCENARIOS_PATH"] = os.path.normpath(
        "%s/subprojects/gst-devtools/validate/data/scenarios" % SCRIPTDIR)
    env["GST_VALIDATE_PLUGIN_PATH"] = os.path.normpath(
        "%s/subprojects/gst-devtools/validate/plugins" % options.builddir)
    env["GST_VALIDATE_APPS_DIR"] = os.path.normpath(
        "%s/subprojects/gst-editing-services/tests/validate" % SCRIPTDIR)
    prepend_env_var(env, "PATH", os.path.normpath(
        "%s/subprojects/gst-devtools/validate/tools" % options.builddir))
    prepend_env_var(env, "PATH", os.path.join(SCRIPTDIR, 'meson'))
    env["GST_VERSION"] = options.gst_version
    env["GST_ENV"] = 'gst-' + options.gst_version
    env["GST_PLUGIN_SYSTEM_PATH"] = ""
    env["GST_PLUGIN_SCANNER"] = os.path.normpath(
        "%s/subprojects/gstreamer/libs/gst/helpers/gst-plugin-scanner" % options.builddir)
    env["GST_PTP_HELPER"] = os.path.normpath(
        "%s/subprojects/gstreamer/libs/gst/helpers/gst-ptp-helper" % options.builddir)
    env["GST_REGISTRY"] = os.path.normpath(options.builddir + "/registry.dat")

    sharedlib_reg = re.compile(r'\.so|\.dylib|\.dll')
    typelib_reg = re.compile(r'.*\.typelib$')
    pluginpath_reg = re.compile(r'lib.*' + re.escape(os.path.normpath('/gstreamer-1.0/')))

    if os.name is 'nt':
        lib_path_envvar = 'PATH'
    elif platform.system() == 'Darwin':
        lib_path_envvar = 'DYLD_LIBRARY_PATH'
    else:
        lib_path_envvar = 'LD_LIBRARY_PATH'

    prepend_env_var(env, "GST_PLUGIN_PATH", os.path.join(SCRIPTDIR, 'subprojects',
                                                        'gst-python', 'plugin'))
    prepend_env_var(env, "GST_PLUGIN_PATH", os.path.join(PREFIX_DIR, 'lib',
                                                        'gstreamer-1.0'))
    prepend_env_var(env, "PATH", os.path.join(PREFIX_DIR, 'bin'))
    prepend_env_var(env, lib_path_envvar, os.path.join(PREFIX_DIR, 'lib'))
    prepend_env_var(env, "GST_VALIDATE_SCENARIOS_PATH", os.path.join(
        PREFIX_DIR, 'share', 'gstreamer-1.0', 'validate', 'scenarios'))
    prepend_env_var(env, "GI_TYPELIB_PATH", os.path.join(PREFIX_DIR, 'lib',
                                                         'lib', 'girepository-1.0'))

    meson, mesonconf, mesonintrospect = get_meson()
    targets_s = subprocess.check_output([sys.executable, mesonintrospect, options.builddir, '--targets'])
    targets = json.loads(targets_s.decode())
    paths = set()
    for target in targets:
        filename = target['filename']
        root = os.path.dirname(filename)
        if typelib_reg.search(filename):
            prepend_env_var(env, "GI_TYPELIB_PATH",
                            os.path.join(options.builddir, root))
        elif sharedlib_reg.search(filename):
            if target.get('type') != "shared library":
                continue
            if pluginpath_reg.search(os.path.normpath(target.get('install_filename'))):
                prepend_env_var(env, "GST_PLUGIN_PATH", os.path.join(options.builddir, root))
                continue

            prepend_env_var(env, lib_path_envvar,
                            os.path.join(options.builddir, root))
        elif target.get('type') == 'executable' and target.get('installed'):
            paths.add(os.path.join(options.builddir, root))

    for p in paths:
        prepend_env_var(env, 'PATH', p)

    presets = set()
    encoding_targets = set()
    pkg_dirs = set()
    if '--installed' in subprocess.check_output([sys.executable, mesonintrospect, '-h']).decode():
        installed_s = subprocess.check_output([sys.executable, mesonintrospect,
                                               options.builddir, '--installed'])
        for path, installpath in json.loads(installed_s.decode()).items():
            if path.endswith('.prs'):
                presets.add(os.path.dirname(path))
            elif path.endswith('.gep'):
                encoding_targets.add(
                    os.path.abspath(os.path.join(os.path.dirname(path), '..')))
            elif path.endswith('.pc'):
                # Is there a -uninstalled pc file for this file?
                uninstalled = "{0}-uninstalled.pc".format(path[:-3])
                if os.path.exists(uninstalled):
                    pkg_dirs.add(os.path.dirname(path))

        for p in presets:
            prepend_env_var(env, 'GST_PRESET_PATH', p)

        for t in encoding_targets:
            prepend_env_var(env, 'GST_ENCODING_TARGET_PATH', t)

        for pkg_dir in pkg_dirs:
            prepend_env_var(env, "PKG_CONFIG_PATH", pkg_dir)
    prepend_env_var(env, "PKG_CONFIG_PATH", os.path.join(options.builddir,
                                                         'subprojects',
                                                         'gst-plugins-good',
                                                         'pkgconfig'))

    mesonpath = os.path.join(SCRIPTDIR, "meson")
    if os.path.join(mesonpath):
        # Add meson/ into PYTHONPATH if we are using a local meson
        prepend_env_var(env, 'PYTHONPATH', mesonpath)

    return env


def python_env(options, unset_env=False):
    """
    Setup our overrides_hack.py as sitecustomize.py script in user
    site-packages if unset_env=False, else unset, previously set
    env.
    """
    subprojects_path = os.path.join(options.builddir, "subprojects")
    gst_python_path = os.path.join(SCRIPTDIR, "subprojects", "gst-python")
    if not os.path.exists(os.path.join(subprojects_path, "gst-python")) or \
            not os.path.exists(gst_python_path):
        return False

    sitepackages = site.getusersitepackages()
    if not sitepackages:
        return False

    sitecustomize = os.path.join(sitepackages, "sitecustomize.py")
    overrides_hack = os.path.join(gst_python_path, "testsuite", "overrides_hack.py")

    if not unset_env:
        if os.path.exists(sitecustomize):
            if os.path.realpath(sitecustomize) == overrides_hack:
                print("Customize user site script already linked to the GStreamer one")
                return False

            old_sitecustomize = os.path.join(sitepackages,
                                            "old.sitecustomize.gstuninstalled.py")
            shutil.move(sitecustomize, old_sitecustomize)
        elif not os.path.exists(sitepackages):
            os.makedirs(sitepackages)

        os.symlink(overrides_hack, sitecustomize)
        return os.path.realpath(sitecustomize) == overrides_hack
    else:
        if not os.path.realpath(sitecustomize) == overrides_hack:
            return False

        os.remove(sitecustomize)
        old_sitecustomize = os.path.join(sitepackages,
                                            "old.sitecustomize.gstuninstalled.py")

        if os.path.exists(old_sitecustomize):
            shutil.move(old_sitecustomize, sitecustomize)

        return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="gstreamer-uninstalled")

    parser.add_argument("--builddir",
                        default=os.path.join(SCRIPTDIR, "build"),
                        help="The meson build directory")
    parser.add_argument("--srcdir",
                        default=SCRIPTDIR,
                        help="The top level source directory")
    parser.add_argument("--gst-version", default="master",
                        help="The GStreamer major version")
    options, args = parser.parse_known_args()

    if not os.path.exists(options.builddir):
        print("GStreamer not built in %s\n\nBuild it and try again" %
              options.builddir)
        exit(1)

    if not os.path.exists(options.srcdir):
        print("The specified source dir does not exist" %
              options.srcdir)
        exit(1)

    if not args:
        if os.name is 'nt':
            args = [os.environ.get("COMSPEC", r"C:\WINDOWS\system32\cmd.exe")]
        else:
            args = [os.environ.get("SHELL", os.path.realpath("/bin/sh"))]
        if "bash" in args[0]:
            bashrc = os.path.expanduser('~/.bashrc')
            if os.path.exists(bashrc):
                tmprc = tempfile.NamedTemporaryFile(mode='w')
                with open(bashrc, 'r') as src:
                    shutil.copyfileobj(src, tmprc)
                tmprc.write('\nexport PS1="[gst-%s] $PS1"' % options.gst_version)
                tmprc.flush()
                # Let the GC remove the tmp file
                args.append("--rcfile")
                args.append(tmprc.name)
    python_set = python_env(options)
    try:
        exit(subprocess.call(args, cwd=options.srcdir,
                             env=get_subprocess_env(options)))
    except subprocess.CalledProcessError as e:
        exit(e.returncode)
    finally:
        if python_set:
            python_env(options, unset_env=True)
