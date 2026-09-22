// How the shell starts the plugin's two programs: the daemon (bin/battles,
// from Service.qml) and the control script (bin/hyprbattles-ctl, from the
// battle screen and the bar panel).
//
// Both are started by a fixed interpreter rather than by whatever `python3`
// is first on the shell's $PATH, with -I so no PYTHON* variable and no user
// site directory can change what they import - and with the shell's
// environment cleared first, so nothing that changes how a program loads
// (LD_PRELOAD, LD_LIBRARY_PATH, PYTHONPATH, PATH) is inherited. What they
// get instead is a fixed $PATH and the short list of session variables
// below, passed through by name: where the sockets are, which display,
// which bus. Once the plugin is enabled these programs run without anybody
// asking, so what they run must not depend on what the session was handed.
//
// lib/tools.py does the same for what the daemon starts in turn, with the
// same two lists; a test keeps them equal.

import QtQuick
import Quickshell
import Quickshell.Io

QtObject {
    id: launcher

    // The interpreter, and the flag that keeps the environment out of it.
    readonly property var python: ["/usr/bin/python3", "-I"]

    // What a child may look up a program in. Root's directories only.
    readonly property string path: "/usr/local/bin:/usr/bin:/bin:/usr/share/omarchy/bin"

    // What the session tells a child, by name. Same list as tools.PASSED.
    readonly property var passed: [
        "HOME",
        "LANG",
        "XDG_RUNTIME_DIR",
        "XDG_CONFIG_HOME",
        "XDG_STATE_HOME",
        "XDG_DATA_HOME",
        "WAYLAND_DISPLAY",
        "DBUS_SESSION_BUS_ADDRESS",
        "HYPRLAND_INSTANCE_SIGNATURE",
        "HYPRBATTLES_ASSETS"
    ]

    readonly property var environment: {
        var env = { "PATH": launcher.path }
        for (var i = 0; i < launcher.passed.length; i++) {
            var name = launcher.passed[i]
            var value = Quickshell.env(name)
            if (value !== undefined && value !== null && String(value) !== "")
                env[name] = String(value)
        }
        return env
    }

    // The argv that runs `script` with `args`.
    function command(script, args) {
        return launcher.python.concat([script]).concat(args || [])
    }

    // Run it and forget it, with the same interpreter and the same
    // environment a Process here gets.
    function detach(script, args) {
        Quickshell.execDetached({
            command: launcher.command(script, args),
            environment: launcher.environment,
            clearEnvironment: true
        })
    }
}
