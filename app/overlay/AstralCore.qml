import QtQuick
import QtQuick3D

Item {
    id: root
    property real energy: 0.0
    property string state: "idle"

    anchors.fill: parent

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
            brightness: 1.8
            color: "#b9ecff"
        }

        PointLight {
            position: Qt.vector3d(0, 80, 260)
            brightness: 2.0 + root.energy * 3.0
            color: "#62d8ff"
        }

        Node {
            id: coreNode
            eulerRotation.y: 20 + sin(rotationClock * 0.7) * 8
            eulerRotation.x: sin(rotationClock * 0.45) * 6
            scale: Qt.vector3d(
                1.0 + root.energy * 0.10,
                1.0 + root.energy * 0.10,
                1.0 + root.energy * 0.10
            )

            Model {
                id: core
                source: "#Sphere"
                scale: Qt.vector3d(1.55, 1.55, 1.55)
                materials: PrincipledMaterial {
                    baseColor: "#66dfff"
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
                    opacity: 0.18 + root.energy * 0.10
                    emissiveFactor: Qt.vector3d(0.05, 0.15, 0.45)
                }
            }
        }

        Node {
            id: ringA
            eulerRotation.x: 65
            eulerRotation.y: rotationClock * 34
            Model {
                source: "#Torus"
                scale: Qt.vector3d(1.35, 1.35, 1.35)
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
            id: ringB
            eulerRotation.x: -55
            eulerRotation.z: 30
            eulerRotation.y: -rotationClock * 25
            Model {
                source: "#Torus"
                scale: Qt.vector3d(1.62, 1.62, 1.62)
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
            id: ringC
            eulerRotation.y: 90
            eulerRotation.z: rotationClock * 18
            Model {
                source: "#Torus"
                scale: Qt.vector3d(1.95, 1.95, 1.95)
                materials: PrincipledMaterial {
                    baseColor: "#55cfff"
                    metalness: 0.65
                    roughness: 0.22
                    emissiveFactor: Qt.vector3d(0.05, 0.35, 0.8)
                    opacity: 0.28
                }
            }
        }

        Model {
            source: "#Sphere"
            scale: Qt.vector3d(2.5, 2.5, 2.5)
            materials: PrincipledMaterial {
                baseColor: "#52d8ff"
                opacity: 0.025 + root.energy * 0.015
                transmissionFactor: 0.8
                emissiveFactor: Qt.vector3d(0.04, 0.15, 0.35)
            }
        }
    }

    NumberAnimation {
        id: rotationClock
        property: "rotationClock"
        from: 0
        to: 360
        duration: 24000
        loops: Animation.Infinite
        running: true
    }

    property real rotationClock: 0

    Timer {
        interval: 16
        running: true
        repeat: true
        onTriggered: root.rotationClock = (root.rotationClock + 0.24) % 360
    }
}
