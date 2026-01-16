/**
 * WebXR Body Tracking Testbed
 * 
 * This application demonstrates the WebXR Body Tracking API by:
 * 1. Requesting a WebXR session with body-tracking feature
 * 2. Reading body joint poses each frame
 * 3. Logging skeleton data to console
 * 4. Rendering joints as cubes and bones as cylinders
 */

// ============================================================================
// CONSTANTS
// ============================================================================

// Skeleton format types
const SKELETON_FORMAT = {
    STANDARD: 'standard',
    PICO: 'pico'
};

// Track the current skeleton format detected
let currentSkeletonFormat = SKELETON_FORMAT.STANDARD;

// All body joints defined in the WebXR Body Tracking spec (standard)
const BODY_JOINTS = [
    // Torso
    "hips", "spine-lower", "spine-middle", "spine-upper", "chest", "neck", "head",
    // Left arm
    "left-shoulder", "left-scapula", "left-arm-upper", "left-arm-lower", "left-hand-wrist-twist",
    // Right arm
    "right-shoulder", "right-scapula", "right-arm-upper", "right-arm-lower", "right-hand-wrist-twist",
    // Left hand
    "left-hand-palm", "left-hand-wrist",
    "left-hand-thumb-metacarpal", "left-hand-thumb-phalanx-proximal", "left-hand-thumb-phalanx-distal", "left-hand-thumb-tip",
    "left-hand-index-metacarpal", "left-hand-index-phalanx-proximal", "left-hand-index-phalanx-intermediate", "left-hand-index-phalanx-distal", "left-hand-index-tip",
    "left-hand-middle-phalanx-metacarpal", "left-hand-middle-phalanx-proximal", "left-hand-middle-phalanx-intermediate", "left-hand-middle-phalanx-distal", "left-hand-middle-tip",
    "left-hand-ring-metacarpal", "left-hand-ring-phalanx-proximal", "left-hand-ring-phalanx-intermediate", "left-hand-ring-phalanx-distal", "left-hand-ring-tip",
    "left-hand-little-metacarpal", "left-hand-little-phalanx-proximal", "left-hand-little-phalanx-intermediate", "left-hand-little-phalanx-distal", "left-hand-little-tip",
    // Right hand
    "right-hand-palm", "right-hand-wrist",
    "right-hand-thumb-metacarpal", "right-hand-thumb-phalanx-proximal", "right-hand-thumb-phalanx-distal", "right-hand-thumb-tip",
    "right-hand-index-metacarpal", "right-hand-index-phalanx-proximal", "right-hand-index-phalanx-intermediate", "right-hand-index-phalanx-distal", "right-hand-index-tip",
    "right-hand-middle-metacarpal", "right-hand-middle-phalanx-proximal", "right-hand-middle-phalanx-intermediate", "right-hand-middle-phalanx-distal", "right-hand-middle-tip",
    "right-hand-ring-metacarpal", "right-hand-ring-phalanx-proximal", "right-hand-ring-phalanx-intermediate", "right-hand-ring-phalanx-distal", "right-hand-ring-tip",
    "right-hand-little-metacarpal", "right-hand-little-phalanx-proximal", "right-hand-little-phalanx-intermediate", "right-hand-little-phalanx-distal", "right-hand-little-tip",
    // Left leg
    "left-upper-leg", "left-lower-leg", "left-foot-ankle-twist", "left-foot-ankle", "left-foot-subtalar", "left-foot-transverse", "left-foot-ball",
    // Right leg
    "right-upper-leg", "right-lower-leg", "right-foot-ankle-twist", "right-foot-ankle", "right-foot-subtalar", "right-foot-transverse", "right-foot-ball"
];

// Bone connections (pairs of joints to draw cylinders between)
const BONE_CONNECTIONS = [
    // Spine
    ["hips", "spine-lower"],
    ["spine-lower", "spine-middle"],
    ["spine-middle", "spine-upper"],
    ["spine-upper", "chest"],
    ["chest", "neck"],
    ["neck", "head"],
    
    // Left arm
    ["chest", "left-shoulder"],
    ["left-shoulder", "left-scapula"],
    ["left-scapula", "left-arm-upper"],
    ["left-arm-upper", "left-arm-lower"],
    ["left-arm-lower", "left-hand-wrist-twist"],
    ["left-hand-wrist-twist", "left-hand-wrist"],
    
    // Right arm
    ["chest", "right-shoulder"],
    ["right-shoulder", "right-scapula"],
    ["right-scapula", "right-arm-upper"],
    ["right-arm-upper", "right-arm-lower"],
    ["right-arm-lower", "right-hand-wrist-twist"],
    ["right-hand-wrist-twist", "right-hand-wrist"],
    
    // Left hand
    ["left-hand-wrist", "left-hand-palm"],
    ["left-hand-wrist", "left-hand-thumb-metacarpal"],
    ["left-hand-thumb-metacarpal", "left-hand-thumb-phalanx-proximal"],
    ["left-hand-thumb-phalanx-proximal", "left-hand-thumb-phalanx-distal"],
    ["left-hand-thumb-phalanx-distal", "left-hand-thumb-tip"],
    ["left-hand-wrist", "left-hand-index-metacarpal"],
    ["left-hand-index-metacarpal", "left-hand-index-phalanx-proximal"],
    ["left-hand-index-phalanx-proximal", "left-hand-index-phalanx-intermediate"],
    ["left-hand-index-phalanx-intermediate", "left-hand-index-phalanx-distal"],
    ["left-hand-index-phalanx-distal", "left-hand-index-tip"],
    ["left-hand-wrist", "left-hand-middle-phalanx-metacarpal"],
    ["left-hand-middle-phalanx-metacarpal", "left-hand-middle-phalanx-proximal"],
    ["left-hand-middle-phalanx-proximal", "left-hand-middle-phalanx-intermediate"],
    ["left-hand-middle-phalanx-intermediate", "left-hand-middle-phalanx-distal"],
    ["left-hand-middle-phalanx-distal", "left-hand-middle-tip"],
    ["left-hand-wrist", "left-hand-ring-metacarpal"],
    ["left-hand-ring-metacarpal", "left-hand-ring-phalanx-proximal"],
    ["left-hand-ring-phalanx-proximal", "left-hand-ring-phalanx-intermediate"],
    ["left-hand-ring-phalanx-intermediate", "left-hand-ring-phalanx-distal"],
    ["left-hand-ring-phalanx-distal", "left-hand-ring-tip"],
    ["left-hand-wrist", "left-hand-little-metacarpal"],
    ["left-hand-little-metacarpal", "left-hand-little-phalanx-proximal"],
    ["left-hand-little-phalanx-proximal", "left-hand-little-phalanx-intermediate"],
    ["left-hand-little-phalanx-intermediate", "left-hand-little-phalanx-distal"],
    ["left-hand-little-phalanx-distal", "left-hand-little-tip"],
    
    // Right hand
    ["right-hand-wrist", "right-hand-palm"],
    ["right-hand-wrist", "right-hand-thumb-metacarpal"],
    ["right-hand-thumb-metacarpal", "right-hand-thumb-phalanx-proximal"],
    ["right-hand-thumb-phalanx-proximal", "right-hand-thumb-phalanx-distal"],
    ["right-hand-thumb-phalanx-distal", "right-hand-thumb-tip"],
    ["right-hand-wrist", "right-hand-index-metacarpal"],
    ["right-hand-index-metacarpal", "right-hand-index-phalanx-proximal"],
    ["right-hand-index-phalanx-proximal", "right-hand-index-phalanx-intermediate"],
    ["right-hand-index-phalanx-intermediate", "right-hand-index-phalanx-distal"],
    ["right-hand-index-phalanx-distal", "right-hand-index-tip"],
    ["right-hand-wrist", "right-hand-middle-metacarpal"],
    ["right-hand-middle-metacarpal", "right-hand-middle-phalanx-proximal"],
    ["right-hand-middle-phalanx-proximal", "right-hand-middle-phalanx-intermediate"],
    ["right-hand-middle-phalanx-intermediate", "right-hand-middle-phalanx-distal"],
    ["right-hand-middle-phalanx-distal", "right-hand-middle-tip"],
    ["right-hand-wrist", "right-hand-ring-metacarpal"],
    ["right-hand-ring-metacarpal", "right-hand-ring-phalanx-proximal"],
    ["right-hand-ring-phalanx-proximal", "right-hand-ring-phalanx-intermediate"],
    ["right-hand-ring-phalanx-intermediate", "right-hand-ring-phalanx-distal"],
    ["right-hand-ring-phalanx-distal", "right-hand-ring-tip"],
    ["right-hand-wrist", "right-hand-little-metacarpal"],
    ["right-hand-little-metacarpal", "right-hand-little-phalanx-proximal"],
    ["right-hand-little-phalanx-proximal", "right-hand-little-phalanx-intermediate"],
    ["right-hand-little-phalanx-intermediate", "right-hand-little-phalanx-distal"],
    ["right-hand-little-phalanx-distal", "right-hand-little-tip"],
    
    // Left leg
    ["hips", "left-upper-leg"],
    ["left-upper-leg", "left-lower-leg"],
    ["left-lower-leg", "left-foot-ankle-twist"],
    ["left-foot-ankle-twist", "left-foot-ankle"],
    ["left-foot-ankle", "left-foot-subtalar"],
    ["left-foot-subtalar", "left-foot-transverse"],
    ["left-foot-transverse", "left-foot-ball"],
    
    // Right leg
    ["hips", "right-upper-leg"],
    ["right-upper-leg", "right-lower-leg"],
    ["right-lower-leg", "right-foot-ankle-twist"],
    ["right-foot-ankle-twist", "right-foot-ankle"],
    ["right-foot-ankle", "right-foot-subtalar"],
    ["right-foot-subtalar", "right-foot-transverse"],
    ["right-foot-transverse", "right-foot-ball"]
];

// ============================================================================
// PICO BODY TRACKING (XR_BD_body_tracking) - 24 joints
// Based on WebXR Body Tracking Module (Pico) proposal
// ============================================================================

// All body joints defined in the Pico/ByteDance body tracking spec
const BODY_JOINTS_PICO = [
    "pelvis",           // 0 - XR_BODY_JOINT_PELVIS_BD
    "left-hip",         // 1 - XR_BODY_JOINT_LEFT_HIP_BD
    "right-hip",        // 2 - XR_BODY_JOINT_RIGHT_HIP_BD
    "spine-1",          // 3 - XR_BODY_JOINT_SPINE1_BD
    "left-knee",        // 4 - XR_BODY_JOINT_LEFT_KNEE_BD
    "right-knee",       // 5 - XR_BODY_JOINT_RIGHT_KNEE_BD
    "spine-2",          // 6 - XR_BODY_JOINT_SPINE2_BD
    "left-ankle",       // 7 - XR_BODY_JOINT_LEFT_ANKLE_BD
    "right-ankle",      // 8 - XR_BODY_JOINT_RIGHT_ANKLE_BD
    "spine-3",          // 9 - XR_BODY_JOINT_SPINE3_BD
    "left-foot",        // 10 - XR_BODY_JOINT_LEFT_FOOT_BD
    "right-foot",       // 11 - XR_BODY_JOINT_RIGHT_FOOT_BD
    "neck",             // 12 - XR_BODY_JOINT_NECK_BD
    "left-collar",      // 13 - XR_BODY_JOINT_LEFT_COLLAR_BD
    "right-collar",     // 14 - XR_BODY_JOINT_RIGHT_COLLAR_BD
    "head",             // 15 - XR_BODY_JOINT_HEAD_BD
    "left-shoulder",    // 16 - XR_BODY_JOINT_LEFT_SHOULDER_BD
    "right-shoulder",   // 17 - XR_BODY_JOINT_RIGHT_SHOULDER_BD
    "left-elbow",       // 18 - XR_BODY_JOINT_LEFT_ELBOW_BD
    "right-elbow",      // 19 - XR_BODY_JOINT_RIGHT_ELBOW_BD
    "left-wrist",       // 20 - XR_BODY_JOINT_LEFT_WRIST_BD
    "right-wrist",      // 21 - XR_BODY_JOINT_RIGHT_WRIST_BD
    "left-hand",        // 22 - XR_BODY_JOINT_LEFT_HAND_BD
    "right-hand"        // 23 - XR_BODY_JOINT_RIGHT_HAND_BD
];

// Bone connections for Pico skeleton (pairs of joints to draw cylinders between)
const BONE_CONNECTIONS_PICO = [
    // Spine
    ["pelvis", "spine-1"],
    ["spine-1", "spine-2"],
    ["spine-2", "spine-3"],
    ["spine-3", "neck"],
    ["neck", "head"],
    
    // Left leg
    ["pelvis", "left-hip"],
    ["left-hip", "left-knee"],
    ["left-knee", "left-ankle"],
    ["left-ankle", "left-foot"],
    
    // Right leg
    ["pelvis", "right-hip"],
    ["right-hip", "right-knee"],
    ["right-knee", "right-ankle"],
    ["right-ankle", "right-foot"],
    
    // Left arm
    ["spine-3", "left-collar"],
    ["left-collar", "left-shoulder"],
    ["left-shoulder", "left-elbow"],
    ["left-elbow", "left-wrist"],
    ["left-wrist", "left-hand"],
    
    // Right arm
    ["spine-3", "right-collar"],
    ["right-collar", "right-shoulder"],
    ["right-shoulder", "right-elbow"],
    ["right-elbow", "right-wrist"],
    ["right-wrist", "right-hand"]
];

// Joint size for cubes (in meters)
const JOINT_SIZE = 0.02;

// Cylinder radius for bones (in meters)
const BONE_RADIUS = 0.008;

// ============================================================================
// SHADERS
// ============================================================================

const VERTEX_SHADER = `
    attribute vec4 aPosition;
    attribute vec3 aNormal;
    
    uniform mat4 uModelMatrix;
    uniform mat4 uViewMatrix;
    uniform mat4 uProjectionMatrix;
    uniform mat3 uNormalMatrix;
    
    varying vec3 vNormal;
    varying vec3 vPosition;
    
    void main() {
        vec4 worldPosition = uModelMatrix * aPosition;
        vPosition = worldPosition.xyz;
        vNormal = uNormalMatrix * aNormal;
        gl_Position = uProjectionMatrix * uViewMatrix * worldPosition;
    }
`;

const FRAGMENT_SHADER = `
    precision mediump float;
    
    uniform vec3 uColor;
    uniform vec3 uLightDirection;
    
    varying vec3 vNormal;
    varying vec3 vPosition;
    
    void main() {
        vec3 normal = normalize(vNormal);
        vec3 lightDir = normalize(uLightDirection);
        
        // Ambient
        float ambient = 0.3;
        
        // Diffuse
        float diffuse = max(dot(normal, lightDir), 0.0);
        
        // Combine
        vec3 finalColor = uColor * (ambient + diffuse * 0.7);
        
        gl_FragColor = vec4(finalColor, 1.0);
    }
`;

// ============================================================================
// GLOBALS
// ============================================================================

let canvas, gl;
let xrSession = null;
let xrRefSpace = null;
let shaderProgram;
let cubeBuffers, cylinderBuffers;
let frameCount = 0;

// Uniform locations
let uniforms = {};

// ============================================================================
// INITIALIZATION
// ============================================================================

async function init() {
    canvas = document.getElementById('glCanvas');
    const statusEl = document.getElementById('status');
    const enterVRBtn = document.getElementById('enterVR');
    
    // Initialize WebGL
    gl = canvas.getContext('webgl', { xrCompatible: true });
    if (!gl) {
        statusEl.textContent = 'WebGL not supported';
        return;
    }
    
    // Setup shaders and geometry
    setupShaders();
    setupGeometry();
    
    // Check WebXR support
    if (!navigator.xr) {
        statusEl.textContent = 'WebXR not supported in this browser';
        return;
    }
    
    // Check for immersive-vr support
    const vrSupported = await navigator.xr.isSessionSupported('immersive-vr');
    if (!vrSupported) {
        statusEl.textContent = 'Immersive VR not supported on this device';
        return;
    }
    
    statusEl.textContent = 'WebXR ready. Click "Enter VR" to start body tracking.';
    enterVRBtn.disabled = false;
    enterVRBtn.addEventListener('click', startXRSession);
    
    // Start non-XR render loop for preview
    requestAnimationFrame(renderNonXR);
}

function setupShaders() {
    // Compile vertex shader
    const vertShader = gl.createShader(gl.VERTEX_SHADER);
    gl.shaderSource(vertShader, VERTEX_SHADER);
    gl.compileShader(vertShader);
    if (!gl.getShaderParameter(vertShader, gl.COMPILE_STATUS)) {
        console.error('Vertex shader error:', gl.getShaderInfoLog(vertShader));
        return;
    }
    
    // Compile fragment shader
    const fragShader = gl.createShader(gl.FRAGMENT_SHADER);
    gl.shaderSource(fragShader, FRAGMENT_SHADER);
    gl.compileShader(fragShader);
    if (!gl.getShaderParameter(fragShader, gl.COMPILE_STATUS)) {
        console.error('Fragment shader error:', gl.getShaderInfoLog(fragShader));
        return;
    }
    
    // Link program
    shaderProgram = gl.createProgram();
    gl.attachShader(shaderProgram, vertShader);
    gl.attachShader(shaderProgram, fragShader);
    gl.linkProgram(shaderProgram);
    if (!gl.getProgramParameter(shaderProgram, gl.LINK_STATUS)) {
        console.error('Program link error:', gl.getProgramInfoLog(shaderProgram));
        return;
    }
    
    // Get uniform locations
    uniforms.modelMatrix = gl.getUniformLocation(shaderProgram, 'uModelMatrix');
    uniforms.viewMatrix = gl.getUniformLocation(shaderProgram, 'uViewMatrix');
    uniforms.projectionMatrix = gl.getUniformLocation(shaderProgram, 'uProjectionMatrix');
    uniforms.normalMatrix = gl.getUniformLocation(shaderProgram, 'uNormalMatrix');
    uniforms.color = gl.getUniformLocation(shaderProgram, 'uColor');
    uniforms.lightDirection = gl.getUniformLocation(shaderProgram, 'uLightDirection');
}

function setupGeometry() {
    cubeBuffers = createCubeBuffers();
    cylinderBuffers = createCylinderBuffers(8);
}

function createCubeBuffers() {
    const s = 0.5; // Half size, will be scaled
    
    // Vertices
    const positions = new Float32Array([
        // Front
        -s, -s,  s,   s, -s,  s,   s,  s,  s,  -s,  s,  s,
        // Back
        -s, -s, -s,  -s,  s, -s,   s,  s, -s,   s, -s, -s,
        // Top
        -s,  s, -s,  -s,  s,  s,   s,  s,  s,   s,  s, -s,
        // Bottom
        -s, -s, -s,   s, -s, -s,   s, -s,  s,  -s, -s,  s,
        // Right
         s, -s, -s,   s,  s, -s,   s,  s,  s,   s, -s,  s,
        // Left
        -s, -s, -s,  -s, -s,  s,  -s,  s,  s,  -s,  s, -s
    ]);
    
    const normals = new Float32Array([
        // Front
        0, 0, 1,  0, 0, 1,  0, 0, 1,  0, 0, 1,
        // Back
        0, 0, -1,  0, 0, -1,  0, 0, -1,  0, 0, -1,
        // Top
        0, 1, 0,  0, 1, 0,  0, 1, 0,  0, 1, 0,
        // Bottom
        0, -1, 0,  0, -1, 0,  0, -1, 0,  0, -1, 0,
        // Right
        1, 0, 0,  1, 0, 0,  1, 0, 0,  1, 0, 0,
        // Left
        -1, 0, 0,  -1, 0, 0,  -1, 0, 0,  -1, 0, 0
    ]);
    
    const indices = new Uint16Array([
        0, 1, 2,  0, 2, 3,    // Front
        4, 5, 6,  4, 6, 7,    // Back
        8, 9, 10,  8, 10, 11,  // Top
        12, 13, 14,  12, 14, 15, // Bottom
        16, 17, 18,  16, 18, 19, // Right
        20, 21, 22,  20, 22, 23  // Left
    ]);
    
    const posBuffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, posBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, positions, gl.STATIC_DRAW);
    
    const normalBuffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, normalBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, normals, gl.STATIC_DRAW);
    
    const indexBuffer = gl.createBuffer();
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, indexBuffer);
    gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, indices, gl.STATIC_DRAW);
    
    return {
        position: posBuffer,
        normal: normalBuffer,
        indices: indexBuffer,
        indexCount: indices.length
    };
}

function createCylinderBuffers(segments) {
    const positions = [];
    const normals = [];
    const indices = [];
    
    // Cylinder along Y axis, from y=0 to y=1, radius=1 (will be scaled)
    for (let i = 0; i <= segments; i++) {
        const angle = (i / segments) * Math.PI * 2;
        const x = Math.cos(angle);
        const z = Math.sin(angle);
        
        // Bottom vertex
        positions.push(x, 0, z);
        normals.push(x, 0, z);
        
        // Top vertex
        positions.push(x, 1, z);
        normals.push(x, 0, z);
    }
    
    // Indices
    for (let i = 0; i < segments; i++) {
        const i0 = i * 2;
        const i1 = i * 2 + 1;
        const i2 = i * 2 + 2;
        const i3 = i * 2 + 3;
        
        indices.push(i0, i2, i1);
        indices.push(i1, i2, i3);
    }
    
    const posBuffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, posBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(positions), gl.STATIC_DRAW);
    
    const normalBuffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, normalBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(normals), gl.STATIC_DRAW);
    
    const indexBuffer = gl.createBuffer();
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, indexBuffer);
    gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, new Uint16Array(indices), gl.STATIC_DRAW);
    
    return {
        position: posBuffer,
        normal: normalBuffer,
        indices: indexBuffer,
        indexCount: indices.length
    };
}

// ============================================================================
// WEBXR SESSION
// ============================================================================

async function startXRSession() {
    try {
        // Request session with body-tracking features (standard and Pico)
        xrSession = await navigator.xr.requestSession('immersive-vr', {
            requiredFeatures: ['local-floor'],
            optionalFeatures: ['body-tracking', 'body-tracking-pico']
        });
        
        console.log('WebXR session started');
        console.log('Body tracking (standard) available:', xrSession.enabledFeatures?.includes('body-tracking') ?? 'unknown');
        console.log('Body tracking (Pico) available:', xrSession.enabledFeatures?.includes('body-tracking-pico') ?? 'unknown');
        
        document.getElementById('overlay').style.display = 'none';
        
        // Setup WebGL for XR
        await gl.makeXRCompatible();
        
        const baseLayer = new XRWebGLLayer(xrSession, gl);
        xrSession.updateRenderState({ baseLayer });
        
        // Get reference space
        xrRefSpace = await xrSession.requestReferenceSpace('local-floor');
        
        // Handle session end
        xrSession.addEventListener('end', onXRSessionEnd);
        
        // Start XR render loop
        xrSession.requestAnimationFrame(onXRFrame);
        
    } catch (error) {
        console.error('Failed to start XR session:', error);
        document.getElementById('status').textContent = 'Failed to start XR: ' + error.message;
    }
}

function onXRSessionEnd() {
    console.log('XR session ended');
    xrSession = null;
    xrRefSpace = null;
    document.getElementById('overlay').style.display = 'flex';
    requestAnimationFrame(renderNonXR);
}

// ============================================================================
// RENDER LOOP
// ============================================================================

function onXRFrame(time, frame) {
    const session = frame.session;
    session.requestAnimationFrame(onXRFrame);
    
    const pose = frame.getViewerPose(xrRefSpace);
    if (!pose) return;
    
    const glLayer = session.renderState.baseLayer;
    gl.bindFramebuffer(gl.FRAMEBUFFER, glLayer.framebuffer);
    
    gl.clearColor(0.1, 0.1, 0.15, 1.0);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    gl.enable(gl.DEPTH_TEST);
    gl.enable(gl.CULL_FACE);
    
    // Get body tracking data - check for both standard and Pico formats
    const body = frame.body;
    const bodyPico = frame.bodyPico;
    let jointPositions = null;
    
    // Try standard body tracking first, then Pico
    const activeBody = body || bodyPico;
    const isPicoFormat = !body && bodyPico;
    
    if (activeBody) {
        jointPositions = {};
        currentSkeletonFormat = isPicoFormat ? SKELETON_FORMAT.PICO : SKELETON_FORMAT.STANDARD;
        
        // Log body data periodically
        if (frameCount % 60 === 0) {
            console.log('=== Body Tracking Data ===');
            console.log('Format:', currentSkeletonFormat);
            console.log('Body size (number of joints):', activeBody.size);
        }
        
        // Iterate through all joints
        for (const [jointName, jointSpace] of activeBody) {
            const jointPose = frame.getPose(jointSpace, xrRefSpace);
            
            if (jointPose) {
                const pos = jointPose.transform.position;
                const rot = jointPose.transform.orientation;
                
                jointPositions[jointName] = {
                    position: [pos.x, pos.y, pos.z],
                    orientation: [rot.x, rot.y, rot.z, rot.w]
                };
                
                // Log joint data periodically
                if (frameCount % 60 === 0) {
                    console.log(`Joint: ${jointName}`);
                    console.log(`  Position: (${pos.x.toFixed(3)}, ${pos.y.toFixed(3)}, ${pos.z.toFixed(3)})`);
                }
            }
        }
        
        // Update UI
        const formatLabel = isPicoFormat ? ' (Pico)' : ' (Standard)';
        document.getElementById('jointCount').textContent = 
            `Tracking ${Object.keys(jointPositions).length} joints${formatLabel}`;
    } else {
        // No body tracking available
        if (frameCount % 120 === 0) {
            console.log('Body tracking not available in this frame');
        }
        document.getElementById('jointCount').textContent = 'Body tracking not available';
    }
    
    // Render for each view (eye)
    for (const view of pose.views) {
        const viewport = glLayer.getViewport(view);
        gl.viewport(viewport.x, viewport.y, viewport.width, viewport.height);
        
        renderScene(view.projectionMatrix, view.transform.inverse.matrix, jointPositions);
    }
    
    frameCount++;
}

function renderNonXR() {
    if (xrSession) return;
    
    // Resize canvas
    canvas.width = canvas.clientWidth * window.devicePixelRatio;
    canvas.height = canvas.clientHeight * window.devicePixelRatio;
    
    gl.viewport(0, 0, canvas.width, canvas.height);
    gl.clearColor(0.1, 0.1, 0.15, 1.0);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    gl.enable(gl.DEPTH_TEST);
    gl.enable(gl.CULL_FACE);
    
    // Create simple preview - render both skeleton formats side by side
    const aspect = canvas.width / canvas.height;
    const projMatrix = createPerspectiveMatrix(Math.PI / 4, aspect, 0.1, 100);
    const viewMatrix = createLookAtMatrix([0, 1.5, 4], [0, 1, 0], [0, 1, 0]);
    
    const time = performance.now() / 1000;
    
    // Render standard skeleton on the left
    const standardPositions = createDemoSkeleton(time);
    const standardOffset = offsetSkeleton(standardPositions, -0.8, 0, 0);
    
    // Render Pico skeleton on the right
    const picoPositions = createDemoSkeletonPico(time);
    const picoOffset = offsetSkeleton(picoPositions, 0.8, 0, 0);
    
    renderSceneMultiFormat(projMatrix, viewMatrix, standardOffset, picoOffset);
    
    requestAnimationFrame(renderNonXR);
}

// Offset all joint positions by a given amount
function offsetSkeleton(jointPositions, offsetX, offsetY, offsetZ) {
    const offset = {};
    for (const jointName in jointPositions) {
        const joint = jointPositions[jointName];
        offset[jointName] = {
            position: [joint.position[0] + offsetX, joint.position[1] + offsetY, joint.position[2] + offsetZ],
            orientation: joint.orientation
        };
    }
    return offset;
}

// Render scene with multiple skeleton formats
function renderSceneMultiFormat(projectionMatrix, viewMatrix, standardPositions, picoPositions) {
    gl.useProgram(shaderProgram);
    
    // Set view and projection matrices
    gl.uniformMatrix4fv(uniforms.projectionMatrix, false, projectionMatrix);
    gl.uniformMatrix4fv(uniforms.viewMatrix, false, viewMatrix);
    
    // Set light direction
    gl.uniform3fv(uniforms.lightDirection, [0.5, 1.0, 0.5]);
    
    // Draw standard skeleton (left side)
    if (standardPositions) {
        drawSkeleton(standardPositions, 1.0, SKELETON_FORMAT.STANDARD);
        
        // Draw mirrored standard skeleton facing user
        const mirroredStandard = createMirroredSkeleton(standardPositions, 2.0);
        drawSkeleton(mirroredStandard, 0.7, SKELETON_FORMAT.STANDARD);
    }
    
    // Draw Pico skeleton (right side)
    if (picoPositions) {
        drawSkeleton(picoPositions, 1.0, SKELETON_FORMAT.PICO);
        
        // Draw mirrored Pico skeleton facing user
        const mirroredPico = createMirroredSkeleton(picoPositions, 2.0);
        drawSkeleton(mirroredPico, 0.7, SKELETON_FORMAT.PICO);
    }
}

function renderScene(projectionMatrix, viewMatrix, jointPositions) {
    gl.useProgram(shaderProgram);
    
    // Set view and projection matrices
    gl.uniformMatrix4fv(uniforms.projectionMatrix, false, projectionMatrix);
    gl.uniformMatrix4fv(uniforms.viewMatrix, false, viewMatrix);
    
    // Set light direction
    gl.uniform3fv(uniforms.lightDirection, [0.5, 1.0, 0.5]);
    
    if (!jointPositions) return;
    
    // Draw the original skeleton (user's body)
    drawSkeleton(jointPositions, 1.0);
    
    // Draw a second skeleton facing the user (mirrored and offset)
    const mirroredPositions = createMirroredSkeleton(jointPositions, 2.0); // 2 meters in front
    drawSkeleton(mirroredPositions, 0.7); // Slightly dimmer
}

function createMirroredSkeleton(jointPositions, offsetZ) {
    const mirrored = {};
    
    for (const jointName in jointPositions) {
        const joint = jointPositions[jointName];
        const pos = joint.position;
        
        // Mirror X position and offset Z to place skeleton in front, facing user
        mirrored[jointName] = {
            position: [-pos[0], pos[1], -pos[2] - offsetZ],
            orientation: joint.orientation
        };
    }
    
    return mirrored;
}

function drawSkeleton(jointPositions, brightness, skeletonFormat = null) {
    // Auto-detect skeleton format if not specified
    if (!skeletonFormat) {
        skeletonFormat = detectSkeletonFormat(jointPositions);
    }
    
    // Select appropriate bone connections based on format
    const boneConnections = skeletonFormat === SKELETON_FORMAT.PICO 
        ? BONE_CONNECTIONS_PICO 
        : BONE_CONNECTIONS;
    
    // Draw joints as cubes
    for (const jointName in jointPositions) {
        const joint = jointPositions[jointName];
        const color = getJointColor(jointName);
        const adjustedColor = [color[0] * brightness, color[1] * brightness, color[2] * brightness];
        drawCube(joint.position, JOINT_SIZE, adjustedColor);
    }
    
    // Draw bones as cylinders
    for (const [joint1Name, joint2Name] of boneConnections) {
        const joint1 = jointPositions[joint1Name];
        const joint2 = jointPositions[joint2Name];
        
        if (joint1 && joint2) {
            const color = getBoneColor(joint1Name, joint2Name);
            const adjustedColor = [color[0] * brightness, color[1] * brightness, color[2] * brightness];
            drawCylinder(joint1.position, joint2.position, BONE_RADIUS, adjustedColor);
        }
    }
}

// Detect skeleton format based on joint names present
function detectSkeletonFormat(jointPositions) {
    // Check for Pico-specific joints
    if (jointPositions['pelvis'] || jointPositions['spine-1'] || jointPositions['left-collar']) {
        return SKELETON_FORMAT.PICO;
    }
    // Check for standard-specific joints
    if (jointPositions['hips'] || jointPositions['spine-lower'] || jointPositions['chest']) {
        return SKELETON_FORMAT.STANDARD;
    }
    // Default to current detected format
    return currentSkeletonFormat;
}

// ============================================================================
// DRAWING FUNCTIONS
// ============================================================================

function drawCube(position, size, color) {
    const modelMatrix = createTranslationMatrix(position[0], position[1], position[2]);
    const scaleMatrix = createScaleMatrix(size, size, size);
    const finalMatrix = multiplyMatrices(modelMatrix, scaleMatrix);
    
    gl.uniformMatrix4fv(uniforms.modelMatrix, false, finalMatrix);
    gl.uniformMatrix3fv(uniforms.normalMatrix, false, extractNormalMatrix(finalMatrix));
    gl.uniform3fv(uniforms.color, color);
    
    // Bind buffers
    const posLoc = gl.getAttribLocation(shaderProgram, 'aPosition');
    const normLoc = gl.getAttribLocation(shaderProgram, 'aNormal');
    
    gl.bindBuffer(gl.ARRAY_BUFFER, cubeBuffers.position);
    gl.enableVertexAttribArray(posLoc);
    gl.vertexAttribPointer(posLoc, 3, gl.FLOAT, false, 0, 0);
    
    gl.bindBuffer(gl.ARRAY_BUFFER, cubeBuffers.normal);
    gl.enableVertexAttribArray(normLoc);
    gl.vertexAttribPointer(normLoc, 3, gl.FLOAT, false, 0, 0);
    
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, cubeBuffers.indices);
    gl.drawElements(gl.TRIANGLES, cubeBuffers.indexCount, gl.UNSIGNED_SHORT, 0);
}

function drawCylinder(start, end, radius, color) {
    // Calculate cylinder transform
    const dx = end[0] - start[0];
    const dy = end[1] - start[1];
    const dz = end[2] - start[2];
    const length = Math.sqrt(dx*dx + dy*dy + dz*dz);
    
    if (length < 0.001) return;
    
    // Create transformation matrix to position and orient cylinder
    const modelMatrix = createCylinderTransform(start, end, radius, length);
    
    gl.uniformMatrix4fv(uniforms.modelMatrix, false, modelMatrix);
    gl.uniformMatrix3fv(uniforms.normalMatrix, false, extractNormalMatrix(modelMatrix));
    gl.uniform3fv(uniforms.color, color);
    
    // Bind buffers
    const posLoc = gl.getAttribLocation(shaderProgram, 'aPosition');
    const normLoc = gl.getAttribLocation(shaderProgram, 'aNormal');
    
    gl.bindBuffer(gl.ARRAY_BUFFER, cylinderBuffers.position);
    gl.enableVertexAttribArray(posLoc);
    gl.vertexAttribPointer(posLoc, 3, gl.FLOAT, false, 0, 0);
    
    gl.bindBuffer(gl.ARRAY_BUFFER, cylinderBuffers.normal);
    gl.enableVertexAttribArray(normLoc);
    gl.vertexAttribPointer(normLoc, 3, gl.FLOAT, false, 0, 0);
    
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, cylinderBuffers.indices);
    gl.drawElements(gl.TRIANGLES, cylinderBuffers.indexCount, gl.UNSIGNED_SHORT, 0);
}

// ============================================================================
// MATRIX UTILITIES
// ============================================================================

function createPerspectiveMatrix(fov, aspect, near, far) {
    const f = 1.0 / Math.tan(fov / 2);
    const nf = 1 / (near - far);
    
    return new Float32Array([
        f / aspect, 0, 0, 0,
        0, f, 0, 0,
        0, 0, (far + near) * nf, -1,
        0, 0, 2 * far * near * nf, 0
    ]);
}

function createLookAtMatrix(eye, target, up) {
    const zAxis = normalize([eye[0] - target[0], eye[1] - target[1], eye[2] - target[2]]);
    const xAxis = normalize(cross(up, zAxis));
    const yAxis = cross(zAxis, xAxis);
    
    return new Float32Array([
        xAxis[0], yAxis[0], zAxis[0], 0,
        xAxis[1], yAxis[1], zAxis[1], 0,
        xAxis[2], yAxis[2], zAxis[2], 0,
        -dot(xAxis, eye), -dot(yAxis, eye), -dot(zAxis, eye), 1
    ]);
}

function createTranslationMatrix(x, y, z) {
    return new Float32Array([
        1, 0, 0, 0,
        0, 1, 0, 0,
        0, 0, 1, 0,
        x, y, z, 1
    ]);
}

function createScaleMatrix(sx, sy, sz) {
    return new Float32Array([
        sx, 0, 0, 0,
        0, sy, 0, 0,
        0, 0, sz, 0,
        0, 0, 0, 1
    ]);
}

function createCylinderTransform(start, end, radius, length) {
    // Direction vector
    const dx = end[0] - start[0];
    const dy = end[1] - start[1];
    const dz = end[2] - start[2];
    
    // Normalize
    const dir = normalize([dx, dy, dz]);
    
    // Find perpendicular vectors
    let up = [0, 1, 0];
    if (Math.abs(dir[1]) > 0.99) {
        up = [1, 0, 0];
    }
    
    const right = normalize(cross(up, dir));
    const newUp = cross(dir, right);
    
    // Create rotation matrix that aligns Y axis with direction
    // Then scale and translate
    return new Float32Array([
        right[0] * radius, right[1] * radius, right[2] * radius, 0,
        dir[0] * length, dir[1] * length, dir[2] * length, 0,
        newUp[0] * radius, newUp[1] * radius, newUp[2] * radius, 0,
        start[0], start[1], start[2], 1
    ]);
}

function multiplyMatrices(a, b) {
    const result = new Float32Array(16);
    for (let i = 0; i < 4; i++) {
        for (let j = 0; j < 4; j++) {
            result[j * 4 + i] = 
                a[i] * b[j * 4] +
                a[i + 4] * b[j * 4 + 1] +
                a[i + 8] * b[j * 4 + 2] +
                a[i + 12] * b[j * 4 + 3];
        }
    }
    return result;
}

function extractNormalMatrix(m) {
    // Extract upper-left 3x3 and transpose (for uniform scale this works)
    return new Float32Array([
        m[0], m[1], m[2],
        m[4], m[5], m[6],
        m[8], m[9], m[10]
    ]);
}

function normalize(v) {
    const len = Math.sqrt(v[0]*v[0] + v[1]*v[1] + v[2]*v[2]);
    if (len === 0) return [0, 0, 0];
    return [v[0]/len, v[1]/len, v[2]/len];
}

function cross(a, b) {
    return [
        a[1]*b[2] - a[2]*b[1],
        a[2]*b[0] - a[0]*b[2],
        a[0]*b[1] - a[1]*b[0]
    ];
}

function dot(a, b) {
    return a[0]*b[0] + a[1]*b[1] + a[2]*b[2];
}

// ============================================================================
// COLOR UTILITIES
// ============================================================================

function getJointColor(jointName) {
    // Color coding by body part (supports both standard and Pico joint names)
    
    // Head/neck - skin tone
    if (jointName.includes('head') || jointName.includes('neck')) {
        return [0.9, 0.7, 0.5];
    }
    
    // Torso - blue (standard: spine/chest/hips, Pico: pelvis/spine-1/2/3)
    if (jointName.includes('spine') || jointName.includes('chest') || 
        jointName.includes('hips') || jointName === 'pelvis') {
        return [0.2, 0.6, 0.9];
    }
    
    // Left arm/hand - red (includes collar, shoulder, elbow, wrist, hand)
    if (jointName.includes('left-hand') || jointName.includes('left-arm') || 
        jointName.includes('left-shoulder') || jointName.includes('left-scapula') ||
        jointName.includes('left-collar') || jointName.includes('left-elbow') ||
        jointName.includes('left-wrist')) {
        return [0.9, 0.3, 0.3];
    }
    
    // Right arm/hand - green (includes collar, shoulder, elbow, wrist, hand)
    if (jointName.includes('right-hand') || jointName.includes('right-arm') || 
        jointName.includes('right-shoulder') || jointName.includes('right-scapula') ||
        jointName.includes('right-collar') || jointName.includes('right-elbow') ||
        jointName.includes('right-wrist')) {
        return [0.3, 0.9, 0.3];
    }
    
    // Left leg - orange (hip, knee, ankle, foot)
    if (jointName.includes('left-')) {
        return [0.9, 0.5, 0.2];
    }
    
    // Right leg - purple (hip, knee, ankle, foot)
    if (jointName.includes('right-')) {
        return [0.5, 0.2, 0.9];
    }
    
    return [0.8, 0.8, 0.8]; // Default gray
}

function getBoneColor(joint1Name, joint2Name) {
    // Use slightly darker version of joint color
    const color = getJointColor(joint1Name);
    return [color[0] * 0.7, color[1] * 0.7, color[2] * 0.7];
}

// ============================================================================
// DEMO SKELETON (for preview when not in VR)
// ============================================================================

// Create demo skeleton in standard format
function createDemoSkeleton(time) {
    const positions = {};
    
    // Animate slightly
    const breathe = Math.sin(time * 2) * 0.02;
    const sway = Math.sin(time) * 0.05;
    
    // Torso
    positions['hips'] = { position: [sway, 0.9, 0], orientation: [0, 0, 0, 1] };
    positions['spine-lower'] = { position: [sway, 1.0, 0], orientation: [0, 0, 0, 1] };
    positions['spine-middle'] = { position: [sway, 1.1, 0], orientation: [0, 0, 0, 1] };
    positions['spine-upper'] = { position: [sway, 1.2, 0], orientation: [0, 0, 0, 1] };
    positions['chest'] = { position: [sway, 1.3 + breathe, 0], orientation: [0, 0, 0, 1] };
    positions['neck'] = { position: [sway, 1.45 + breathe, 0], orientation: [0, 0, 0, 1] };
    positions['head'] = { position: [sway, 1.6 + breathe, 0], orientation: [0, 0, 0, 1] };
    
    // Left arm
    const leftArmSwing = Math.sin(time * 1.5) * 0.1;
    positions['left-shoulder'] = { position: [0.15 + sway, 1.4 + breathe, 0], orientation: [0, 0, 0, 1] };
    positions['left-scapula'] = { position: [0.2 + sway, 1.35 + breathe, 0], orientation: [0, 0, 0, 1] };
    positions['left-arm-upper'] = { position: [0.3 + sway, 1.25 + breathe, leftArmSwing], orientation: [0, 0, 0, 1] };
    positions['left-arm-lower'] = { position: [0.35 + sway, 1.05 + breathe, leftArmSwing * 1.5], orientation: [0, 0, 0, 1] };
    positions['left-hand-wrist-twist'] = { position: [0.38 + sway, 0.88 + breathe, leftArmSwing * 1.8], orientation: [0, 0, 0, 1] };
    positions['left-hand-wrist'] = { position: [0.4 + sway, 0.85 + breathe, leftArmSwing * 2], orientation: [0, 0, 0, 1] };
    positions['left-hand-palm'] = { position: [0.4 + sway, 0.82 + breathe, leftArmSwing * 2], orientation: [0, 0, 0, 1] };
    
    // Right arm
    const rightArmSwing = Math.sin(time * 1.5 + Math.PI) * 0.1;
    positions['right-shoulder'] = { position: [-0.15 + sway, 1.4 + breathe, 0], orientation: [0, 0, 0, 1] };
    positions['right-scapula'] = { position: [-0.2 + sway, 1.35 + breathe, 0], orientation: [0, 0, 0, 1] };
    positions['right-arm-upper'] = { position: [-0.3 + sway, 1.25 + breathe, rightArmSwing], orientation: [0, 0, 0, 1] };
    positions['right-arm-lower'] = { position: [-0.35 + sway, 1.05 + breathe, rightArmSwing * 1.5], orientation: [0, 0, 0, 1] };
    positions['right-hand-wrist-twist'] = { position: [-0.38 + sway, 0.88 + breathe, rightArmSwing * 1.8], orientation: [0, 0, 0, 1] };
    positions['right-hand-wrist'] = { position: [-0.4 + sway, 0.85 + breathe, rightArmSwing * 2], orientation: [0, 0, 0, 1] };
    positions['right-hand-palm'] = { position: [-0.4 + sway, 0.82 + breathe, rightArmSwing * 2], orientation: [0, 0, 0, 1] };
    
    // Left leg
    positions['left-upper-leg'] = { position: [0.1 + sway, 0.85, 0], orientation: [0, 0, 0, 1] };
    positions['left-lower-leg'] = { position: [0.1 + sway * 0.5, 0.45, 0], orientation: [0, 0, 0, 1] };
    positions['left-foot-ankle-twist'] = { position: [0.1 + sway * 0.3, 0.1, 0], orientation: [0, 0, 0, 1] };
    positions['left-foot-ankle'] = { position: [0.1 + sway * 0.2, 0.08, 0], orientation: [0, 0, 0, 1] };
    positions['left-foot-subtalar'] = { position: [0.1 + sway * 0.1, 0.05, 0.02], orientation: [0, 0, 0, 1] };
    positions['left-foot-transverse'] = { position: [0.1, 0.03, 0.06], orientation: [0, 0, 0, 1] };
    positions['left-foot-ball'] = { position: [0.1, 0.02, 0.12], orientation: [0, 0, 0, 1] };
    
    // Right leg
    positions['right-upper-leg'] = { position: [-0.1 + sway, 0.85, 0], orientation: [0, 0, 0, 1] };
    positions['right-lower-leg'] = { position: [-0.1 + sway * 0.5, 0.45, 0], orientation: [0, 0, 0, 1] };
    positions['right-foot-ankle-twist'] = { position: [-0.1 + sway * 0.3, 0.1, 0], orientation: [0, 0, 0, 1] };
    positions['right-foot-ankle'] = { position: [-0.1 + sway * 0.2, 0.08, 0], orientation: [0, 0, 0, 1] };
    positions['right-foot-subtalar'] = { position: [-0.1 + sway * 0.1, 0.05, 0.02], orientation: [0, 0, 0, 1] };
    positions['right-foot-transverse'] = { position: [-0.1, 0.03, 0.06], orientation: [0, 0, 0, 1] };
    positions['right-foot-ball'] = { position: [-0.1, 0.02, 0.12], orientation: [0, 0, 0, 1] };
    
    return positions;
}

// Create demo skeleton in Pico format (24 joints)
function createDemoSkeletonPico(time) {
    const positions = {};
    
    // Animate slightly
    const breathe = Math.sin(time * 2) * 0.02;
    const sway = Math.sin(time) * 0.05;
    
    // Torso/Spine
    positions['pelvis'] = { position: [sway, 0.95, 0], orientation: [0, 0, 0, 1] };
    positions['spine-1'] = { position: [sway, 1.05, 0], orientation: [0, 0, 0, 1] };
    positions['spine-2'] = { position: [sway, 1.15, 0], orientation: [0, 0, 0, 1] };
    positions['spine-3'] = { position: [sway, 1.3 + breathe, 0], orientation: [0, 0, 0, 1] };
    positions['neck'] = { position: [sway, 1.45 + breathe, 0], orientation: [0, 0, 0, 1] };
    positions['head'] = { position: [sway, 1.6 + breathe, 0], orientation: [0, 0, 0, 1] };
    
    // Left arm
    const leftArmSwing = Math.sin(time * 1.5) * 0.1;
    positions['left-collar'] = { position: [0.1 + sway, 1.35 + breathe, 0], orientation: [0, 0, 0, 1] };
    positions['left-shoulder'] = { position: [0.2 + sway, 1.35 + breathe, 0], orientation: [0, 0, 0, 1] };
    positions['left-elbow'] = { position: [0.35 + sway, 1.1 + breathe, leftArmSwing], orientation: [0, 0, 0, 1] };
    positions['left-wrist'] = { position: [0.4 + sway, 0.88 + breathe, leftArmSwing * 1.5], orientation: [0, 0, 0, 1] };
    positions['left-hand'] = { position: [0.42 + sway, 0.82 + breathe, leftArmSwing * 1.8], orientation: [0, 0, 0, 1] };
    
    // Right arm
    const rightArmSwing = Math.sin(time * 1.5 + Math.PI) * 0.1;
    positions['right-collar'] = { position: [-0.1 + sway, 1.35 + breathe, 0], orientation: [0, 0, 0, 1] };
    positions['right-shoulder'] = { position: [-0.2 + sway, 1.35 + breathe, 0], orientation: [0, 0, 0, 1] };
    positions['right-elbow'] = { position: [-0.35 + sway, 1.1 + breathe, rightArmSwing], orientation: [0, 0, 0, 1] };
    positions['right-wrist'] = { position: [-0.4 + sway, 0.88 + breathe, rightArmSwing * 1.5], orientation: [0, 0, 0, 1] };
    positions['right-hand'] = { position: [-0.42 + sway, 0.82 + breathe, rightArmSwing * 1.8], orientation: [0, 0, 0, 1] };
    
    // Left leg
    positions['left-hip'] = { position: [0.1 + sway, 0.9, 0], orientation: [0, 0, 0, 1] };
    positions['left-knee'] = { position: [0.1 + sway * 0.5, 0.5, 0], orientation: [0, 0, 0, 1] };
    positions['left-ankle'] = { position: [0.1 + sway * 0.2, 0.08, 0], orientation: [0, 0, 0, 1] };
    positions['left-foot'] = { position: [0.1, 0.03, 0.08], orientation: [0, 0, 0, 1] };
    
    // Right leg
    positions['right-hip'] = { position: [-0.1 + sway, 0.9, 0], orientation: [0, 0, 0, 1] };
    positions['right-knee'] = { position: [-0.1 + sway * 0.5, 0.5, 0], orientation: [0, 0, 0, 1] };
    positions['right-ankle'] = { position: [-0.1 + sway * 0.2, 0.08, 0], orientation: [0, 0, 0, 1] };
    positions['right-foot'] = { position: [-0.1, 0.03, 0.08], orientation: [0, 0, 0, 1] };
    
    return positions;
}

// ============================================================================
// START
// ============================================================================

init();

