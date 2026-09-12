import QtQuick
import QtQuick3D

Item {
    id: root
    property real energy: 0.0
    property string state: "idle"
    property real motion: 0.0

    anchors.fill: parent

    readonly property real statePulse: {
        if (state === "listening") return 0.10
        if (state === "thinking" || state === "planning") return 0.16
        if (state === "executing" || state === "verifying") return 0.22
        if (state === "speaking") return 0.28
        if (state === "success") return 0.18
        if (state === "error") return 0.06
        return 0.03
    }

    View3D {
        anchors.fill: parent
        camera: camera
        renderMode: View3D.Offscreen
        environment: SceneEnvironment {
            backgroundMode: SceneEnvironment.Transparent
            clearColor: "transparent"
            antialiasingMode: SceneEnvironment.MSAA
            antialiasingQuality: SceneEnvironment.High
        }

        PerspectiveCamera {
            id: camera
            position: Qt.vector3d(0, 0, 620)
            clipNear: 1
            clipFar: 2000
        }

        DirectionalLight {
            eulerRotation.x: -35
            eulerRotation.y: 25
            brightness: 1.8 + root.statePulse * 3
            color: "#b9ecff"
        }

        PointLight {
            position: Qt.vector3d(0, 80, 260)
            brightness: 2.0 + root.energy * 3.0 + root.statePulse * 5
            color: root.state === "error" ? "#ff6b9a" : root.state === "success" ? "#75ffbd" : "#62d8ff"
        }

        Node {
            id: coreNode
            eulerRotation.y: root.motion * 34
            eulerRotation.x: Math.sin(root.motion * 0.7) * 8
            scale: Qt.vector3d(
                1.0 + root.energy * 0.10 + root.statePulse,
                1.0 + root.energy * 0.10 + root.statePulse,
                1.0 + root.energy * 0.10 + root.statePulse
            )

            Model {
                source: "#Sphere"
                scale: Qt.vector3d(1.55, 1.55, 1.55)
                materials: PrincipledMaterial {
                    baseColor: root.state === "error" ? "#ff5d8f" : root.state === "success" ? "#72ffc0" : "#66dfff"
                    metalness: 0.55
                    roughness: 0.18
                    emissiveFactor: Qt.vector3d(0.18, 0.65, 1.0)
                    opacity: 0.94
                }
            }

            Model {
                source: "#Sphere"
                scale: Qt.vector3d(1.72, 1.72, 1.72)
                materials: PrincipledMaterial {
                    baseColor: "#193a9b"
                    metalness: 0.35
                    roughness: 0.3
                    transmissionFactor: 0.35
                    opacity: 0.18 + root.energy * 0.10 + root.statePulse * 0.2
                    emissiveFactor: Qt.vector3d(0.05, 0.15, 0.45)
                }
            }
        }

        // The previous implementation used an inline ProceduralMesh component.
        // QML on the supported PySide6 range rejects that inline component syntax
        // before the scene can even load. Use only built-in Qt Quick 3D primitives
        // here so the Astral Core remains compatible with Qt 6.8.
        Node {
            id: ringNodeA
            eulerRotation.x: 65
            eulerRotation.y: root.motion * 34

            Model {
                source: "#Cylinder"
                scale: Qt.vector3d(2.05, 0.035, 2.05)
                materials: PrincipledMaterial {
                    baseColor: "#72e8ff"
                    metalness: 0.8
                    roughness: 0.15
                    emissiveFactor: Qt.vector3d(0.1, 0.55, 1.0)
                    opacity: 0.72
                }
            }
        }

        Node {
            id: ringNodeB
            eulerRotation.x: -55
            eulerRotation.z: 30
            eulerRotation.y: -root.motion * 25

            Model {
                source: "#Cylinder"
                scale: Qt.vector3d(2.45, 0.028, 2.45)
                materials: PrincipledMaterial {
                    baseColor: "#9b83ff"
                    metalness: 0.7
                    roughness: 0.2
                    emissiveFactor: Qt.vector3d(0.25, 0.15, 0.9)
                    opacity: 0.48
                }
            }
        }

        Node {
            id: ringNodeC
            eulerRotation.y: 90
            eulerRotation.z: root.motion * 18

            Model {
                source: "#Cylinder"
                scale: Qt.vector3d(2.95, 0.022, 2.95)
                materials: PrincipledMaterial {
                    baseColor: "#55cfff"
                    metalness: 0.65
                    roughness: 0.22
                    emissiveFactor: Qt.vector3d(0.05, 0.35, 0.8)
                    opacity: 0.28 + root.statePulse
                }
            }
        }

        Model {
            source: "#Sphere"
            scale: Qt.vector3d(2.5, 2.5, 2.5)
            materials: PrincipledMaterial {
                baseColor: "#52d8ff"
                opacity: 0.025 + root.energy * 0.015 + root.statePulse * 0.04
                transmissionFactor: 0.8
                emissiveFactor: Qt.vector3d(0.04, 0.15, 0.35)
            }
        }
    }

    Timer {
        interval: 16
        running: true
        repeat: true
        onTriggered: root.motion = (root.motion + 0.004) % 6.28318
    }
}
