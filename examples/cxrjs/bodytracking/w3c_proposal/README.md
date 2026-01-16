# WebXR Body Tracking (Pico)

> ⚠️ ***PRELIMINARY PROPOSAL FOR DISCUSSION. NOT FOR PUBLIC RELEASE OR SUBMISSION TO W3C.***

The [WebXR Body Tracking (Pico) Specification][this-spec] adds body tracking support in WebXR using the ByteDance body tracking joint set (XR_BD_body_tracking).  Based on [existing body tracking spec](https://github.com/immersive-web/body-tracking).

This specification defines a 24-joint body skeleton that corresponds to the joints defined in the OpenXR XR_BD_body_tracking extension, which is supported on Pico devices.

## Specifications

* [WebXR Body Tracking (Pico)][this-spec]: Body Tracking support in WebXR using ByteDance joint set
* [Explainer](explainer.md)

## Joint Set

This specification uses the 24-joint skeleton from the ByteDance body tracking extension:

| Joint Name | OpenXR Equivalent |
|------------|-------------------|
| pelvis | XR_BODY_JOINT_PELVIS_BD |
| left-hip | XR_BODY_JOINT_LEFT_HIP_BD |
| right-hip | XR_BODY_JOINT_RIGHT_HIP_BD |
| spine-1 | XR_BODY_JOINT_SPINE1_BD |
| left-knee | XR_BODY_JOINT_LEFT_KNEE_BD |
| right-knee | XR_BODY_JOINT_RIGHT_KNEE_BD |
| spine-2 | XR_BODY_JOINT_SPINE2_BD |
| left-ankle | XR_BODY_JOINT_LEFT_ANKLE_BD |
| right-ankle | XR_BODY_JOINT_RIGHT_ANKLE_BD |
| spine-3 | XR_BODY_JOINT_SPINE3_BD |
| left-foot | XR_BODY_JOINT_LEFT_FOOT_BD |
| right-foot | XR_BODY_JOINT_RIGHT_FOOT_BD |
| neck | XR_BODY_JOINT_NECK_BD |
| left-collar | XR_BODY_JOINT_LEFT_COLLAR_BD |
| right-collar | XR_BODY_JOINT_RIGHT_COLLAR_BD |
| head | XR_BODY_JOINT_HEAD_BD |
| left-shoulder | XR_BODY_JOINT_LEFT_SHOULDER_BD |
| right-shoulder | XR_BODY_JOINT_RIGHT_SHOULDER_BD |
| left-elbow | XR_BODY_JOINT_LEFT_ELBOW_BD |
| right-elbow | XR_BODY_JOINT_RIGHT_ELBOW_BD |
| left-wrist | XR_BODY_JOINT_LEFT_WRIST_BD |
| right-wrist | XR_BODY_JOINT_RIGHT_WRIST_BD |
| left-hand | XR_BODY_JOINT_LEFT_HAND_BD |
| right-hand | XR_BODY_JOINT_RIGHT_HAND_BD |

### Related specifications
* [WebXR Device API - Level 1][webxrspec]: Main specification for JavaScript API for accessing VR and AR devices, including sensors and head-mounted displays.
* [OpenXR XR_BD_body_tracking](https://registry.khronos.org/OpenXR/specs/1.1/html/xrspec.html#XR_BD_body_tracking): The OpenXR extension this specification is based on.

See also [list of all specifications with detailed status in Working Group and Community Group](https://www.w3.org/immersive-web/list_spec.html). 

## Relevant Links

* [Immersive Web Community Group][webxrcg]
* [Immersive Web Working Group Charter][wgcharter]

## Communication

* [Immersive Web Working Group][webxrwg]
* [Immersive Web Community Group][webxrcg]
* [GitHub issues list](https://github.com/immersive-web/body-tracking/issues)
* [`public-immersive-web` mailing list][publiclist]

## Maintainers

To generate the spec document (`index.html`) from the `index.bs` [Bikeshed][bikeshed] document:

```sh
bikeshed spec
```

## Tests

For normative changes, a corresponding
[web-platform-tests][wpt] PR is highly appreciated. Typically,
both PRs will be merged at the same time. Note that a test change that contradicts the spec should
not be merged before the corresponding spec change. If testing is not practical, please explain why
and if appropriate [file a web-platform-tests issue][wptissue]
to follow up later. Add the `type:untestable` or `type:missing-coverage` label as appropriate.


## License

Per the [`LICENSE.md`](LICENSE.md) file:

> All documents in this Repository are licensed by contributors under the  [W3C Software and Document License](https://www.w3.org/Consortium/Legal/copyright-software).

# Summary

For more information about this proposal, please read the [explainer](explainer.md) and issues/PRs.

<!-- Links -->
[this-spec]: https://immersive-web.github.io/body-tracking/
[CoC]: https://immersive-web.github.io/homepage/code-of-conduct.html
[webxrwg]: https://w3.org/immersive-web
[cgproposals]: https://github.com/immersive-web/proposals
[webxrspec]: https://immersive-web.github.io/webxr/
[webxrcg]: https://www.w3.org/community/immersive-web/
[wgcharter]: https://www.w3.org/2020/05/immersive-Web-wg-charter.html
[webxrref]: https://immersive-web.github.io/webxr-reference/
[publiclist]: https://lists.w3.org/Archives/Public/public-immersive-web-wg/
[bikeshed]: https://github.com/tabatkins/bikeshed
[wpt]: https://github.com/web-platform-tests/wpt
[wptissue]: https://github.com/web-platform-tests/wpt/issues/new
