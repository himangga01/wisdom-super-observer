import { createServer } from 'node:http';
import type { AddressInfo } from 'node:net';
import { test, expect } from '@playwright/test';

const recorderTypes = [
  'video/webm;codecs=vp8,opus',
  'video/webm;codecs=vp9,opus',
  'video/webm;codecs=h264,opus',
  'video/mp4;codecs=avc1.42E01E,mp4a.40.2',
  'audio/webm;codecs=opus',
  'audio/mp4;codecs=mp4a.40.2',
];

test('records read-only browser platform capabilities on a trustworthy local origin', async ({ browser, page, context }, testInfo) => {
  const server = createServer((_request, response) => {
    response.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
    response.end('<!doctype html><html lang="en"><title>TVT platform preflight</title><body>Local browser probe</body></html>');
  });

  await new Promise<void>((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });

  try {
    const port = (server.address() as AddressInfo).port;
    const origin = `http://127.0.0.1:${port}`;
    const response = await page.goto(origin);
    expect(response?.status()).toBe(200);

    const capabilities = await page.evaluate(async (types) => {
      const storageEstimate = await navigator.storage?.estimate().then(
        ({ quota, usage }) => ({ status: 'OK', quotaBytes: quota ?? null, usageBytes: usage ?? null }),
        (error) => ({ status: 'ERROR', error: String(error) }),
      ) ?? { status: 'UNAVAILABLE' };
      const storagePersisted = await navigator.storage?.persisted?.().then(
        (value) => ({ status: 'OK', value }),
        (error) => ({ status: 'ERROR', error: String(error) }),
      ) ?? { status: 'UNAVAILABLE' };

      const mediaRecorderPresent = typeof MediaRecorder !== 'undefined';
      return {
        origin: location.origin,
        userAgent: navigator.userAgent,
        locale: navigator.language,
        timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        secureContext: isSecureContext,
        mediaDevices: {
          present: 'mediaDevices' in navigator,
          cameraAndMicrophoneApi: typeof navigator.mediaDevices?.getUserMedia === 'function',
          displayCaptureApi: typeof navigator.mediaDevices?.getDisplayMedia === 'function',
        },
        mediaRecorder: {
          present: mediaRecorderPresent,
          types: Object.fromEntries(types.map((type) => [type, mediaRecorderPresent && MediaRecorder.isTypeSupported(type)])),
        },
        webRtc: {
          peerConnection: typeof RTCPeerConnection !== 'undefined',
          videoSenderCodecs: typeof RTCRtpSender !== 'undefined'
            ? (RTCRtpSender.getCapabilities('video')?.codecs ?? []).map((codec) => codec.mimeType)
            : [],
          audioSenderCodecs: typeof RTCRtpSender !== 'undefined'
            ? (RTCRtpSender.getCapabilities('audio')?.codecs ?? []).map((codec) => codec.mimeType)
            : [],
        },
        push: {
          serviceWorkerApi: 'serviceWorker' in navigator,
          pushManagerApi: typeof PushManager !== 'undefined',
          notificationApi: typeof Notification !== 'undefined',
          notificationPermission: typeof Notification !== 'undefined' ? Notification.permission : 'UNAVAILABLE',
        },
        storage: {
          indexedDbApi: typeof indexedDB !== 'undefined',
          localStorageApi: typeof localStorage !== 'undefined',
          sessionStorageApi: typeof sessionStorage !== 'undefined',
          storageEstimate,
          storagePersisted,
          filePickerApi: 'showOpenFilePicker' in window,
          webShareApi: typeof navigator.share === 'function',
        },
        visibility: { initial: document.visibilityState },
      };
    }, recorderTypes);

    await page.evaluate(() => {
      (window as Window & { preflightVisibility?: string[] }).preflightVisibility = [];
      document.addEventListener('visibilitychange', () => {
        (window as Window & { preflightVisibility: string[] }).preflightVisibility.push(document.visibilityState);
      });
    });
    const secondTab = await context.newPage();
    await secondTab.goto(origin);
    await secondTab.bringToFront();
    await page.waitForTimeout(250);
    const background = await page.evaluate(() => document.visibilityState);
    await secondTab.close();
    await page.bringToFront();
    await page.waitForTimeout(250);
    const visibility = await page.evaluate(() => ({
      resumed: document.visibilityState,
      events: (window as Window & { preflightVisibility: string[] }).preflightVisibility,
    }));

    const report = {
      profile: testInfo.project.name,
      browserVersion: browser.version(),
      ...capabilities,
      visibility: { ...capabilities.visibility, background, ...visibility },
      scope: {
        permissionPrompt: 'UNTESTED',
        mediaCapture: 'UNTESTED',
        serviceWorkerRegistration: 'UNTESTED',
        pushSubscriptionAndDelivery: 'UNTESTED',
        closedClientAndLockScreen: 'UNTESTED',
      },
    };
    expect(report.origin).toBe(origin);
    expect(report.secureContext).toBe(true);
    await testInfo.attach('browser-capabilities.json', {
      body: Buffer.from(JSON.stringify(report, null, 2)),
      contentType: 'application/json',
    });
    console.log(`TVT_PREFLIGHT ${JSON.stringify(report)}`);
  } finally {
    await new Promise<void>((resolve) => server.close(() => resolve()));
  }
});
