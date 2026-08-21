// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Owning handle to any FlatBuffer table, used in place of the generated object-API
// (`-T`) types.
//
// A `-T` type is a tree of std::vector / std::string / std::unique_ptr members that
// only exists after an UnPack. Handing one out means a tracker either copies it per
// read or lends out storage it will refill next frame. `Serialized<T>` instead points
// straight at the encoded bytes: readers address the buffer, so there is no unpack
// step, no per-field allocation, and no `-T` in any public signature.
//
// Two properties the rest of the tracker stack leans on:
//
//   - Copying is a refcount bump, and nothing rewrites the bytes once encoded, so a copy
//     taken this frame stays valid after the tracker moves on. Consumers hold snapshots,
//     not views into live tracker storage.
//
//     Immutability is a contract, not an enforcement: the Python bindings hand out
//     writable NumPy views over the joint arrays, because NumPy cannot export a
//     read-only array over DLPack before 2.1 (see schema_array_views.h). Writing through
//     one changes what every holder of that buffer sees, so callers that intend to
//     modify must copy first.
//   - `ptr_` need not be the buffer root. Narrowing to a nested table shares the
//     parent's owner and just re-points, so one allocation backs a whole tree of views.
//
// An empty handle (`get() == nullptr`, contextually false) means "no table here".
//
// Nullable on purpose, and for a format-level reason rather than a domain one: a
// FlatBuffers table field is optional, so the generated accessor already returns null
// when it is unset. A handle is that pointer plus its owner, so a non-nullable handle
// could represent less than the pointer it wraps -- `narrow()` would have to hand back
// an optional, which relocates the null rather than removing it, and costs the
// by-reference returns and default-constructibility the tracker impls rely on.
//
// This type is deliberately schema-agnostic: it knows how to own and re-point a buffer
// and nothing about any field.

#pragma once

#include <flatbuffers/flatbuffers.h>

#include <cassert>
#include <memory>
#include <span>
#include <type_traits>
#include <utility>
#include <vector>

namespace core
{

template <typename T>
class Serialized
{
public:
    //! No table: no buffer, `get()` is null. See the note on nullability above.
    Serialized() = default;

    /*!
     * @brief Wraps `ptr` and keeps `owner` alive for as long as this handle (or any
     *        copy, or any handle narrowed from it) exists.
     *
     * `owner` is type-erased because the bytes can be backed by a builder's
     * `DetachedBuffer`, a `std::vector<uint8_t>` read off the wire, or the owner of a
     * parent handle this one was narrowed from. Prefer `adopt()` / `narrow()` over
     * calling this directly.
     */
    Serialized(std::shared_ptr<const void> owner, const T* ptr) : owner_(std::move(owner)), ptr_(ptr)
    {
    }

    Serialized(const Serialized&) = default;
    Serialized& operator=(const Serialized&) = default;

    //! Moving empties the source, same as `reset()`. The compiler-generated versions would
    //! move `owner_` out but copy `ptr_`, leaving a handle that tests true and dereferences
    //! into a buffer it no longer has a claim on -- and that `narrow()` would hand an
    //! owner-less pointer out of.
    Serialized(Serialized&& other) noexcept
        : owner_(std::move(other.owner_)),
          ptr_(std::exchange(other.ptr_, nullptr)),
          buffer_(std::exchange(other.buffer_, {}))
    {
    }

    Serialized& operator=(Serialized&& other) noexcept
    {
        owner_ = std::move(other.owner_);
        ptr_ = std::exchange(other.ptr_, nullptr);
        buffer_ = std::exchange(other.buffer_, {});
        return *this;
    }

    /*!
     * @brief Takes ownership of a finished builder's buffer, rooted at `T`.
     *
     * The builder must have had `Finish()` called on an offset of type `T`; it is
     * reset by the `Release()` and can be reused for the next frame.
     */
    static Serialized adopt(flatbuffers::FlatBufferBuilder& fbb)
    {
        auto owner = std::make_shared<const flatbuffers::DetachedBuffer>(fbb.Release());
        return Serialized(owner, flatbuffers::GetRoot<T>(owner->data()), { owner->data(), owner->size() });
    }

    /*!
     * @brief Takes ownership of encoded bytes rooted at `T`, as read off the wire.
     *
     * The counterpart to the builder overload for the other owner kind named above: a
     * buffer that arrived already encoded, so there is nothing to build and nothing to
     * copy. `bytes` must hold a complete buffer whose root table is `T`.
     */
    static Serialized adopt(std::vector<uint8_t>&& bytes)
    {
        auto owner = std::make_shared<const std::vector<uint8_t>>(std::move(bytes));
        return Serialized(owner, flatbuffers::GetRoot<T>(owner->data()), { owner->data(), owner->size() });
    }

    /*!
     * @brief The whole encoded buffer, when this handle is the one that adopted it.
     *
     * Lets already-encoded bytes reach a sink that takes a pointer and a length -- a
     * tensor push, an MCAP write -- without decoding and re-encoding them on the way.
     *
     * Empty unless the handle came from `adopt()`. `narrow()` deliberately does not carry
     * it: a narrowed handle points *inside* a buffer whose root is some other table, so
     * those bytes are not a buffer rooted at `T` and handing them to a reader expecting
     * one would be wrong.
     */
    std::span<const uint8_t> buffer() const noexcept
    {
        return buffer_;
    }

    //! Narrows to a table nested inside this buffer, sharing the owner. Null `ptr`
    //! yields an empty handle, so `narrow(parent->child())` maps an unset nested-table
    //! field onto an absent handle without a branch at the call site.
    template <typename U>
    Serialized<U> narrow(const U* ptr) const
    {
        if (ptr == nullptr)
        {
            return Serialized<U>();
        }

        // Narrowing onto this handle's own table is a copy, so it keeps the bytes: they are
        // still a buffer rooted at U. Only a narrow that re-points *inside* the buffer
        // drops them, because from there they no longer delimit a buffer rooted at U.
        if constexpr (std::is_same_v<U, T>)
        {
            if (ptr == ptr_)
            {
                return Serialized<U>(owner_, ptr, buffer_);
            }
        }

        return Serialized<U>(owner_, ptr);
    }

    //! Encoded table, or null when this handle points at nothing.
    const T* get() const noexcept
    {
        return ptr_;
    }

    //! Precondition: the handle is non-empty. Test with `operator bool` (or reach the
    //! field through a null-safe accessor) before dereferencing.
    const T* operator->() const noexcept
    {
        assert(ptr_ != nullptr && "dereferenced an empty Serialized handle");
        return ptr_;
    }

    //! Same precondition as `operator->`.
    const T& operator*() const noexcept
    {
        assert(ptr_ != nullptr && "dereferenced an empty Serialized handle");
        return *ptr_;
    }

    explicit operator bool() const noexcept
    {
        return ptr_ != nullptr;
    }

    //! Drops the table and releases this handle's claim on the buffer. Spells "the payload
    //! went away" without naming the table type, which the assignment form has to repeat.
    void reset() noexcept
    {
        owner_.reset();
        ptr_ = nullptr;
        buffer_ = {};
    }

private:
    Serialized(std::shared_ptr<const void> owner, const T* ptr, std::span<const uint8_t> buffer)
        : owner_(std::move(owner)), ptr_(ptr), buffer_(buffer)
    {
    }

    std::shared_ptr<const void> owner_;
    const T* ptr_ = nullptr;
    std::span<const uint8_t> buffer_;
};

/*!
 * @brief Encodes a native (`-T`) value into a standalone `Serialized<T>`.
 *
 * The bridge for producers that still assemble a `-T` — a tracker impl filling one
 * from an OpenXR query, or a Python binding constructor taking loose arguments. The
 * `-T` stays a local of the caller; only the encoded buffer escapes.
 */
template <typename T>
Serialized<T> pack(const typename T::NativeTableType& native)
{
    flatbuffers::FlatBufferBuilder fbb;
    fbb.Finish(T::Pack(fbb, &native));
    return Serialized<T>::adopt(fbb);
}

} // namespace core
