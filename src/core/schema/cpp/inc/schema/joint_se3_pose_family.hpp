// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Which tracker family a JointName belongs to.
//
// JointType values are the bases of the JointName blocks, so the family of a joint is the
// greatest JointType not exceeding it. Blocks are not a uniform width (100 for hands, 1000
// for bodies), so do not derive a family by rounding. Driving this off EnumValuesJointType()
// keeps it correct as blocks are added, in whatever order they are declared.

#pragma once

#include <schema/joint_se3_pose_generated.h>

namespace core
{

// UNKNOWN when the value falls below every allocated block, which only JointName_UNKNOWN does.
inline JointType joint_family(JointName joint)
{
    JointType family = JointType_UNKNOWN;
    for (const JointType candidate : EnumValuesJointType())
    {
        if (static_cast<int>(candidate) <= static_cast<int>(joint) &&
            static_cast<int>(candidate) >= static_cast<int>(family))
        {
            family = candidate;
        }
    }
    return family;
}

} // namespace core
