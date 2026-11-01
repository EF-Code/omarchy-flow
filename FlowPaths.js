.pragma library

// Quickshell 0.3 uses qs:/// URLs for scanned QML. Processes need the actual
// filesystem path; file:/// is still used by older Quickshell versions.
function localPath(url) {
    var value = String(url)
    if (!/^(file|qs):\/\/\//.test(value)) return ""
    return decodeURIComponent(value.replace(/^(file|qs):\/\//, ""))
}
