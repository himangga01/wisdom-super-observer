# `TVTOpenSDK` 공개 자료 대조

확인일: 2026-09-27. 목적: APK의 `com.tvt.protocol_sdk.TVTOpenSDK`가 외부 개발자가 사용할 수 있는 공개 SDK인지 확인한다.

## 확인 결과

- 설치 APK의 `TVTOpenSDK.java`는 `/sdk/...` 요청을 라우팅하고 UUID별 콜백을 관리하며, `libProtoSDK.so`의 JNI 메서드를 호출한다. 기존 [호출 맵](../tvt-call-map.md)에 실제 메서드와 오프셋이 정리돼 있다. 따라서 **이 APK 내부의 Java 래퍼/진입점이라는 사실**은 확인된다.
- `"TVTOpenSDK"`, `"com.tvt.protocol_sdk.TVTOpenSDK"`, `"TVTOpenSDK.java"`, `"libProtoSDK.so" TVT`의 공개 웹 검색에서 일치하는 공식 API 문서·배포 소스를 찾지 못했다. **검색 결과 부재가 SDK 비공개나 이용 불가를 증명하지는 않는다.**
- [TVT 공식 다운로드의 SDK 분류](https://www.tvt.net.cn/download/index1191.html)는 존재하지만, 검색 도구가 읽은 목록에는 이름·버전·다운로드 항목이 나타나지 않았다. 이 페이지로 `TVTOpenSDK`의 공개 배포 여부를 확정할 수 없다.
- [TVT 중국어 공식 지원 페이지](https://cn.tvt.net.cn/faq/index1155.html)는 **장치 SDK가 필요하면 영업 담당자에게 문의**하라고 표시한다. 이것은 장치 SDK의 배포 경로에 관한 정보이며, 그 SDK가 APK의 `TVTOpenSDK`와 같은 구성품인지는 확인해 주지 않는다.
- TVT 공식 제품 자료는 장치의 [TVT SDK·ONVIF·RTSP 지원](https://en.tvt.net.cn/products/1840.html)을 설명한다. 특정 장치의 기능 표이며, APK의 `TVTOpenSDK` Java API 사양은 아니다.
- [2BAD/tvt 공개 프로젝트](https://github.com/2BAD/tvt)는 `NET_SDK_*` 장치 라이브러리 호출을 구현한다. 이 프로젝트의 [코드](https://github.com/2BAD/tvt/blob/master/source/lib/sdk.ts)는 `NET_SDK_Init`, `NET_SDK_Login` 등 별도 이름을 사용한다. 따라서 이를 `TVTOpenSDK`의 문서나 동등한 구현으로 간주하지 않는다.

## 판정

현재 `TVTOpenSDK`는 **이 APK에 포함된 TVT 계정/장치 서비스 요청용 Java↔JNI 래퍼**로 설명할 수 있다. 공식 공개 SDK인지, 외부 서버 환경에서 재사용 가능한지, TVT 장치용 별도 `NET_SDK`와 프로토콜/세션을 공유하는지는 미확인이다. 기능별 실제 사용 여부는 요청 클래스 등록, JNI 구현, 앱 호출 지점, 실기기 결과를 차례로 대조한다.
