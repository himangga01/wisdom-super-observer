#pragma once
// Static recovery, 2026-10-03. Exact NetSocket SHA-256:
// ebcfcadc7763086418c26490774c5ce36688fc6d4d2187dd6aae264e84f8806d
// See docs/integrations/tvt-windows-socket-abi.md for state/ownership limits.
// This file performs no DLL loading or native calls.
#include <cstddef>
#include <cstdint>
#include <climits>

#if !defined(_WIN64) || !defined(_M_X64)
#error This recovered calling contract requires MSVC-compatible Windows AMD64.
#endif

class CSocketDataObserver; // Full vendor C++ source interface is unavailable.
template<class T, class U> class CChildPairContainer; // Only NULL is supported here.

namespace tvt_verified {
static_assert(CHAR_BIT == 8 && sizeof(void*) == 8 && sizeof(int) == 4);
static_assert(sizeof(unsigned int) == 4 && sizeof(unsigned short) == 2);
static_assert(sizeof(long) == 4 && sizeof(bool) == 1);

using initial_fn = bool (__cdecl *)(int, int, const char*, unsigned int);
using quit_fn = void (__cdecl *)();
using last_error_fn = unsigned int (__cdecl *)();
using config_fn = void (__cdecl *)(const char*, unsigned int, bool, const char*, unsigned int);
using connect_sn_fn = int (__cdecl *)(unsigned int, const char*, unsigned short);
using connect_result_fn = bool (__cdecl *)(int, int&, unsigned int);
using connected_fn = bool (__cdecl *)(int);
using register_fn = bool (__cdecl *)(int, CSocketDataObserver*, void*, int, int);
using start_fn = bool (__cdecl *)(int);
using stop_fn = void (__cdecl *)(int);
using destroy_fn = void (__cdecl *)(int);
using del_connect_fn = void (__cdecl *)(int);
using unregister_fn = void (__cdecl *)(int);
using greeting_fn = int (__cdecl *)(int, char*, int, bool, unsigned int);
using send_fn = int (__cdecl *)(int, const char*, unsigned __int64,
                               const char*, unsigned __int64,
                               CChildPairContainer<unsigned char*, int>*, unsigned int);

// Physical views supported by the scoped NAT2 dispatch, not vendor C++ declarations.
// NetCommon base constructor/destructor installs only one vptr; sized delete is 8.
// NetSocket uses only data at vtable+8. Its fifth argument is NULL; its sixth is
// RegisterNode's context. Full callback data must be copied before returning.
struct observer_view;
using observer_delete_slot = void* (__cdecl *)(observer_view*, unsigned int);
using observer_data_slot = std::int32_t (__cdecl *)(observer_view*, std::uint32_t,
                                                  void*, std::int32_t, void*, void*);
struct observer_vtable_view {
    observer_delete_slot deleting_destructor;
    observer_data_slot data;
};
struct observer_view { const observer_vtable_view* vptr; };
static_assert(sizeof(observer_view) == 8 && offsetof(observer_view, vptr) == 0);
static_assert(sizeof(observer_vtable_view) == 16);
static_assert(offsetof(observer_vtable_view, data) == 8);

// Fixed dynamic lookup identifiers, independently checked against original PE bytes.
inline constexpr char initial_symbol[] = "?NET_SOCKET_Initial@@YA_NHHPEBDI@Z";
inline constexpr char quit_symbol[] = "?NET_SOCKET_Quit@@YAXXZ";
inline constexpr char last_error_symbol[] = "?NET_SOCKET_GetLastError@@YAIXZ";
inline constexpr char config_symbol[] = "?NET_SOCKET_SetP2PServerAddr@@YAXPEBDI_N0I@Z";
inline constexpr char connect_sn_symbol[] = "?NET_SOCKET_AddConnectByP2P2@@YAHIPEBDG@Z";
inline constexpr char connect_result_symbol[] = "?NET_SOCKET_PopConnectResult@@YA_NHAEAHI@Z";
inline constexpr char connected_symbol[] = "?NET_SOCKET_CheckConnectState@@YA_NH@Z";
inline constexpr char register_symbol[] = "?NET_SOCKET_RegisterNode@@YA_NHPEAVCSocketDataObserver@@PEAXHH@Z";
inline constexpr char start_symbol[] = "?NET_SOCKET_Start@@YA_NH@Z";
inline constexpr char stop_symbol[] = "?NET_SOCKET_Stop@@YAXH@Z";
inline constexpr char destroy_symbol[] = "?NET_SOCKET_DestroyHNetCommunication@@YAXH@Z";
inline constexpr char del_connect_symbol[] = "?NET_SOCKET_DelConnect@@YAXH@Z";
inline constexpr char unregister_symbol[] = "?NET_SOCKET_UnRegisterNode@@YAXH@Z";
inline constexpr char greeting_symbol[] = "?NET_SOCKET_Recv_Immediate@@YAHHPEADH_NI@Z";
inline constexpr char send_symbol[] = "?NET_SOCKET_Send@@YAHHPEBD_K01PEAV?$CChildPairContainer@PEAEH@@I@Z";

inline constexpr std::int32_t connect_pending = 0;
inline constexpr std::int32_t connect_established = 1;
inline constexpr std::int32_t connect_failed = -1;
inline constexpr std::size_t greeting_capacity = 64;
inline constexpr bool native_interrupt_available = false;
inline constexpr bool shutdown_quiescence_verified = false;
inline constexpr bool full_vendor_observer_interface_available = false;
inline constexpr bool generic_immediate_nat2_io_available = false;
inline constexpr bool native_execution_verified = false;
} // namespace tvt_verified
