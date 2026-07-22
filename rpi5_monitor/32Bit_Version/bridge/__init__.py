"""
bridge/ — Python↔QML-Brückenschicht des Power Debug Monitors
================================================================
Diese Pakete kapseln die gesamte Anwendungslogik als QObject-Klassen,
die per Context-Property bzw. qmlRegisterType an das QML-Frontend
(gui_qml/) angebunden werden.

Kein Modul hier importiert QtWidgets — die Bridge-Schicht kennt nur
QtCore/QtGui/QtQml/QtQuick, damit die alte Widgets-GUI (gui/) und die
neue QML-GUI (qml/) parallel im selben Projekt existieren können,
ohne sich gegenseitig zu beeinflussen (siehe Migrationsplan, Phase 0-6).
"""
