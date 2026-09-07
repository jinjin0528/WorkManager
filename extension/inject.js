// inject.js - MAIN world (페이지와 같은 JS 컨텍스트에서 실행됨)
// 역할: 페이지가 서버에 보내는 fetch/XHR 요청 중 과제 목록 API(rmain_0003_01_l001.jct) 응답을 가로채서
//       content.js(isolated world)로 postMessage 전달

(function () {
  console.log("[WorkManager] inject.js 로드됨 (MAIN world)");

  // 타겟 API 파일명 - 과제 목록을 내려주는 요청
  const TARGET_URL_PATTERN = /rmain_0003_01_l001/;

  function sendProjectData(data) {
    window.postMessage(
      {
        source: "workmanager-inject",
        type: "PROJECT_LIST_DATA",
        payload: data,
      },
      "*"
    );
  }

  // fetch 가로채기
  const origFetch = window.fetch;
  window.fetch = async function (...args) {
    const res = await origFetch.apply(this, args);
    const url = typeof args[0] === "string" ? args[0] : args[0]?.url || "";

    if (TARGET_URL_PATTERN.test(url)) {
      res
        .clone()
        .json()
        .then((data) => {
          if (data && data.REC) {
            console.log("[WorkManager] 과제 목록 응답 감지(fetch):", url);
            sendProjectData(data);
          }
        })
        .catch((err) => {
          console.log("[WorkManager] fetch 응답 파싱 실패:", err);
        });
    }
    return res;
  };

  // XMLHttpRequest 가로채기 (이 ERP는 XHR 기반일 가능성이 높음)
  const origOpen = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (method, url, ...rest) {
    this.addEventListener("load", function () {
      if (TARGET_URL_PATTERN.test(url)) {
        try {
          const data = JSON.parse(this.responseText);
          if (data && data.REC) {
            console.log("[WorkManager] 과제 목록 응답 감지(XHR):", url);
            sendProjectData(data);
          }
        } catch (err) {
          console.log("[WorkManager] XHR 응답 파싱 실패:", err);
        }
      }
    });
    return origOpen.call(this, method, url, ...rest);
  };
})();