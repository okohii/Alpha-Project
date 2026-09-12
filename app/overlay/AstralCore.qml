import QtQuick
import QtQuick3D
import QtQuick3D.Helpers

// Qt Quick 3D only provides #Sphere/#Cube/#Cylinder/#Cone/#Rectangle as
// built-in Model sources. Torus is a helper geometry, so keep it procedural
// instead of using the invalid source "#Torus".
component AstralTorus : ProceduralMesh {
    property real radius: 100.0
    property real tubeRadius: 8.0
    property int rings: 48
    property int segments: 20

    property var meshArrays: generateTorus(rings, segments, radius, tubeRadius)

    positions: meshArrays.verts
    normals: meshArrays.normals
    uv0s: meshArrays.uvs
    indexes: meshArrays.indices

    function generateTorus(ringCount: int, segmentCount: int, ringRadius: real, tube: real): var {
        let verts = []
        let normals = []
        let uvs = []
        let indices = []

        for (let i = 0; i <= ringCount; ++i) {
            const u = i / ringCount * Math.PI * 2
            const cu = Math.cos(u)
            const su = Math.sin(u)

            for (let j = 0; j <= segmentCount; ++j) {
                const v = j / segmentCount * Math.PI * 2
                const cv = Math.cos(v)
                const sv = Math.sin(v)

                const centerX = ringRadius * cu
                const centerZ = ringRadius * su
                const px = centerX + tube * cv * cu
                const py = tube * sv
                const pz = centerZ + tube * cv * su

                verts.push(Qt.vector3d(px, py, pz))
                normals.push(Qt.vector3d(cv * cu, sv, cv * su))
                uvs.push(Qt.vector2d(i / ringCount, j / segmentCount))
            }
        }

        for (let i = 0; i < ringCount; ++i) {
            for (let j = 0; j < segmentCount; ++j) {
                const a = (segmentCount + 1) * i + j
                const b = (segmentCount + 1) * (i + 1) + j
                const c = (segmentCount + 1) * (i + 1) + j + 1
                const d = (segmentCount + 1) * i + j + 1
                indices.push(a, d, b)
                indices.push(b, d, c)
            }
        }

        return { verts: verts, normals: normals, uvs: uvs, indices: indices }
    }
}

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

        Node {
            eulerRotation.x: 65
            eulerRotation.y: root.motion * 34
            Model {
                geometry: AstralTorus { radius: 105; tubeRadius: 7; rings: 48; segments: 20 }
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
            eulerRotation.x: -55
            eulerRotation.z: 30
            eulerRotation.y: -root.motion * 25
            Model {
                geometry: AstralTorus { radius: 105; tubeRadius: 6; rings: 48; segments: 20 }
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
            eulerRotation.y: 90
            eulerRotation.z: root.motion * 18
            Model {
                geometry: AstralTorus { radius: 105; tubeRadius: 5; rings: 48; segments: 20 }
                scale: Qt.vector3d(1.95, 1.95, 1.95)
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
