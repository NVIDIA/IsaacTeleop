# WebXR Device API - Body Tracking (Pico)

This document describes a design giving developers access to body-tracking XR systems using the ByteDance body tracking joint set, building on top of the [WebXR device API](https://immersive-web.github.io/webxr/).

This specification corresponds to the OpenXR [XR_BD_body_tracking](https://registry.khronos.org/OpenXR/specs/1.1/html/xrspec.html#XR_BD_body_tracking) extension.

## Use cases and scope

This API primarily exposes the joints of a person's body using a 24-joint skeleton. It can be used to render an avatar in VR scenarios. It does not provide access to a full body mesh or individual finger joints.

## Accessing this API

This API will only be accessible if a `"body-tracking-pico"` [XR feature](https://immersive-web.github.io/webxr/#feature-dependencies) is requested.

This API presents itself as an additional field on `XRFrame`, `bodyPico`. The `bodyPico` attribute will be non-null if the XR device supports body tracking and the feature has been requested.

```js
navigator.xr.requestSession("immersive-vr", {
  optionalFeatures: ["body-tracking-pico"]
}).then((session) => {
  // session supports body tracking on Pico devices
});

function renderFrame(session, frame) {
   if (frame.bodyPico) {
      // render a body using the 24-joint skeleton
      for (const [jointName, jointSpace] of frame.bodyPico) {
         const pose = frame.getPose(jointSpace, referenceSpace);
         if (pose) {
            // render joint at pose.transform
         }
      }
   }
}
```

## Joints

Each body is made up of 24 joints. These correspond to the joints defined in the OpenXR XR_BD_body_tracking extension:

| Joint Name | Description |
|------------|-------------|
| `pelvis` | Center of the hip area |
| `left-hip` | Left hip joint |
| `right-hip` | Right hip joint |
| `spine-1` | Lower spine |
| `left-knee` | Left knee joint |
| `right-knee` | Right knee joint |
| `spine-2` | Middle spine |
| `left-ankle` | Left ankle joint |
| `right-ankle` | Right ankle joint |
| `spine-3` | Upper spine |
| `left-foot` | Left foot |
| `right-foot` | Right foot |
| `neck` | Neck joint |
| `left-collar` | Left collar bone area |
| `right-collar` | Right collar bone area |
| `head` | Head |
| `left-shoulder` | Left shoulder joint |
| `right-shoulder` | Right shoulder joint |
| `left-elbow` | Left elbow joint |
| `right-elbow` | Right elbow joint |
| `left-wrist` | Left wrist joint |
| `right-wrist` | Right wrist joint |
| `left-hand` | Left hand |
| `right-hand` | Right hand |

The joint spaces can be accessed via `XRBodyPico.get()`, for example to access the head joint:

```js
let headJoint = frame.bodyPico.get("head");
let headPose = frame.getPose(headJoint, referenceSpace);
```

All devices which support body tracking will support or emulate all joints, so this method will always return a valid object as long as it is supplied with a valid joint name. If a joint is supported but not currently being tracked, the getter will still produce the `XRBodySpacePico`, but it will return `null` when run through `getPose` (etc).

Each joint space is an `XRSpace`, with its `-Y` direction pointing perpendicular to the skin, outwards from the body, and `-Z` direction pointing along their associated bone, away from the body center. This space will return null poses when the joint loses tracking.

## Displaying body models using this API

Ideally, most of this will be handled by an external library or the framework being used by the user.

A simple skeleton can be displayed as follows:

```js
const boneConnections = [
   // Spine
   ["pelvis", "spine-1"],
   ["spine-1", "spine-2"],
   ["spine-2", "spine-3"],
   ["spine-3", "neck"],
   ["neck", "head"],
   
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
   ["right-wrist", "right-hand"],
   
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
];

function renderSkeleton(frame, referenceSpace, renderer) {
   const body = frame.bodyPico;
   if (!body) return;
   
   // Draw joints
   for (const [jointName, jointSpace] of body) {
      const pose = frame.getPose(jointSpace, referenceSpace);
      if (pose) {
         renderer.drawSphere(pose.transform, 0.02); // 2cm radius spheres
      }
   }
   
   // Draw bones connecting joints
   for (const [joint1, joint2] of boneConnections) {
      const space1 = body.get(joint1);
      const space2 = body.get(joint2);
      const pose1 = frame.getPose(space1, referenceSpace);
      const pose2 = frame.getPose(space2, referenceSpace);
      
      if (pose1 && pose2) {
         renderer.drawCylinder(
            pose1.transform.position,
            pose2.transform.position,
            0.01 // 1cm radius cylinder
         );
      }
   }
}
```

## Privacy and Security Considerations

The concept of exposing body input could pose a risk to users' privacy. For example, data produced by some body-tracking systems could potentially enable sites to infer users' body proportions, movement patterns, or medical conditions.

Implementations are required to employ strategies to mitigate these risks, such as:
- Reducing the precision and sampling rate of data
- Adding noise or rounding data
- Return the same body geometry/size for all users
- Emulating values for joints if the implementation isn't capable of detecting them

This specification requires implementations to include sufficient mitigations to protect users' privacy.

## Appendix: Proposed IDL

```webidl
partial interface XRFrame {
   readonly attribute XRBodyPico? bodyPico;
};

enum XRBodyJointPico {
  "pelvis",
  "left-hip",
  "right-hip",
  "spine-1",
  "left-knee",
  "right-knee",
  "spine-2",
  "left-ankle",
  "right-ankle",
  "spine-3",
  "left-foot",
  "right-foot",
  "neck",
  "left-collar",
  "right-collar",
  "head",
  "left-shoulder",
  "right-shoulder",
  "left-elbow",
  "right-elbow",
  "left-wrist",
  "right-wrist",
  "left-hand",
  "right-hand"
};

interface XRBodySpacePico: XRSpace {
   readonly attribute XRBodyJointPico jointName;
};

interface XRBodyPico {
   iterable<XRBodyJointPico, XRBodySpacePico>;

   readonly attribute unsigned long size;
   XRBodySpacePico get(XRBodyJointPico key);
};
```
