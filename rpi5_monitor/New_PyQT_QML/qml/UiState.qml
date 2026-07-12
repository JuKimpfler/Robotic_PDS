pragma Singleton
import QtQuick

// Kleiner globaler Zustand, damit Touch-Widgets, die exklusive
// Drag-Gesten brauchen (z.B. Joystick), dem umgebenden SwipeView/
// Flickable mitteilen können "gerade nicht wischen/scrollen".
// Als eigenes Singleton (statt Item-ID), damit es auch aus anderen
// .qml-Dateien (anderer ID-Scope) erreichbar ist, siehe Theme.qml.
QtObject {
    // true, solange irgendein Touch-Widget exklusiven Zugriff auf Drag-
    // Gesten braucht (z.B. Joystick wird gerade bedient).
    property int _lockCount: 0
    readonly property bool navigationLocked: _lockCount > 0

    function pushLock() { _lockCount += 1 }
    function popLock() { _lockCount = Math.max(0, _lockCount - 1) }
}
