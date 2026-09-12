import QtQuick
import QtQuick3D

Item {
    id: root
    property real energy: 0.0
    property real peak: 0.0
    property string state: "idle"
    property real motion: 0.0
    anchors.fill: parent

    Behavior on energy { NumberAnimation { duration: 70; easing.type: Easing.OutCubic } }
    Behavior on peak { NumberAnimation { duration: 45; easing.type: Easing.OutCubic } }

    function stateColor() {
        if (state === "listening") return "#62a8ff"
        if (state === "thinking" || state === "planning") return "#9b7cff"
        if (state === "executing") return "#ffb35c"
        if (state === "verifying") return "#ff6bd6"
        if (state === "speaking") return "#63f2c2"
        if (state === "success") return "#72ffad"
        if (state === "error") return "#ff5d86"
        return "#66dfff"
    }

    readonly property color accent: stateColor()
    readonly property real statePulse: state === "speaking" ? 0.16 + energy * 0.30 :
        state === "listening" ? 0.10 + energy * 0.18 :
        state === "executing" || state === "verifying" ? 0.14 : 0.035

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
        PerspectiveCamera { id: camera; position: Qt.vector3d(0, 0, 620); clipNear: 1; clipFar: 2000 }
        DirectionalLight { eulerRotation.x: -35; eulerRotation.y: 25; brightness: 1.5 + root.statePulse * 3; color: root.accent }
        PointLight { position: Qt.vector3d(0, 80, 260); brightness: 1.8 + root.energy * 5 + root.peak * 2; color: root.accent }

        Node {
            id: coreNode
            eulerRotation.y: root.motion * 34
            eulerRotation.x: Math.sin(root.motion * 0.7) * (5 + root.energy * 5)
            scale: Qt.vector3d(
                1.0 + root.energy * 0.16 + root.peak * 0.05 + root.statePulse,
                1.0 + root.energy * 0.16 + root.peak * 0.05 + root.statePulse,
                1.0 + root.energy * 0.16 + root.peak * 0.05 + root.statePulse
            )
            Behavior on scale { Vector3dAnimation { duration: 90; easing.type: Easing.OutCubic } }

            Model { source: "#Sphere"; scale: Qt.vector3d(1.55,1.55,1.55); materials: PrincipledMaterial { baseColor: root.accent; metalness: 0.55; roughness: 0.18; emissiveFactor: Qt.vector3d(root.accent.r*0.42,root.accent.g*0.42,root.accent.b*0.42); opacity: 0.94 } }
            Model { source: "#Sphere"; scale: Qt.vector3d(1.72,1.72,1.72); materials: PrincipledMaterial { baseColor: root.accent; metalness: 0.35; roughness: 0.3; transmissionFactor: 0.35; opacity: 0.14 + root.energy*0.18 + root.statePulse*0.2; emissiveFactor: Qt.vector3d(root.accent.r*0.10,root.accent.g*0.10,root.accent.b*0.10) } }
        }

        Node { id: ringNodeA; eulerRotation.x: 65; eulerRotation.y: root.motion*34 + root.energy*20; Model { source:"#Cylinder"; scale:Qt.vector3d(2.05 + root.energy*0.3,0.035,2.05 + root.energy*0.3); materials:PrincipledMaterial { baseColor:root.accent; metalness:0.8; roughness:0.15; emissiveFactor:Qt.vector3d(root.accent.r*0.08,root.accent.g*0.08,root.accent.b*0.08); opacity:0.72 } } }
        Node { id: ringNodeB; eulerRotation.x:-55; eulerRotation.z:30; eulerRotation.y:-root.motion*25; Model { source:"#Cylinder"; scale:Qt.vector3d(2.45 + root.peak*0.5,0.028,2.45 + root.peak*0.5); materials:PrincipledMaterial { baseColor:root.accent; metalness:0.7; roughness:0.2; emissiveFactor:Qt.vector3d(root.accent.r*0.12,root.accent.g*0.12,root.accent.b*0.12); opacity:0.48 } } }
        Node { id: ringNodeC; eulerRotation.y:90; eulerRotation.z:root.motion*18; Model { source:"#Cylinder"; scale:Qt.vector3d(2.95 + root.energy*0.7,0.022,2.95 + root.energy*0.7); materials:PrincipledMaterial { baseColor:root.accent; metalness:0.65; roughness:0.22; emissiveFactor:Qt.vector3d(root.accent.r*0.05,root.accent.g*0.05,root.accent.b*0.05); opacity:0.22 + root.statePulse + root.energy*0.15 } } }
        Model { source:"#Sphere"; scale:Qt.vector3d(2.5 + root.energy*0.6,2.5 + root.energy*0.6,2.5 + root.energy*0.6); materials:PrincipledMaterial { baseColor:root.accent; opacity:0.02 + root.energy*0.035 + root.statePulse*0.04; transmissionFactor:0.8; emissiveFactor:Qt.vector3d(root.accent.r*0.02,root.accent.g*0.02,root.accent.b*0.02) } }
    }

    Timer { interval:16; running:true; repeat:true; onTriggered: root.motion=(root.motion+0.004 + root.energy*0.003)%6.28318 }
}
