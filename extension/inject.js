// inject.js - MAIN world (페이지와 같은 JS 컨텍스트에서 실행됨)
// 역할: 페이지가 서버에 보내는 fetch/XHR 요청 중 과제 목록 API(rmain_0003_01_l001.jct) 응답을 가로채서
//       content.js(isolated world)로 postMessage 전달

(function () {
  console.log("[WorkManager] inject.js 로드됨 (MAIN world)");

  // 이 ERP는 일부 필드 키에 한글 설명이 괄호로 붙어서 내려옴
  // 예: "INQ_RCV_BAL_AMT(입금잔액)" - 심지어 같은 배열 안에서도
  // 첫 번째 항목만 괄호가 붙고 이후엔 안 붙는 경우가 있어서, 항상 괄호 앞부분만
  // 잘라서 키를 통일시켜야 필드를 안정적으로 읽을 수 있음
  function normalizeKeys(obj) {
    if (!obj || typeof obj !== "object") return obj;
    const result = {};
    for (const key in obj) {
      const baseKey = key.split("(")[0];
      result[baseKey] = obj[key];
    }
    return result;
  }

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

  // -------------------------------------------------------------------
  // 수입결의 상태 능동 조회
  // - 화면 이동 없이, 과제번호를 바꿔가며 rtask_0008_t06_01_r001.jct 를
  //   직접 POST 호출해서 "이 과제 수입결의 됐는지"를 순서대로 확인
  // -------------------------------------------------------------------
  const INCOME_STATUS_URL = "/rtask_0008_t06_01_r001.jct";
  const DELAY_MS = 250; // 서버 부담을 줄이기 위한 요청 간 텀

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  function toHyphenDate(yyyymmdd) {
    if (!yyyymmdd || yyyymmdd.length !== 8) return null;
    return `${yyyymmdd.slice(0, 4)}-${yyyymmdd.slice(4, 6)}-${yyyymmdd.slice(6, 8)}`;
  }

  function todayHyphen() {
    const d = new Date();
    const mm = String(d.getMonth() + 1).padStart(2, "0");
    const dd = String(d.getDate()).padStart(2, "0");
    return `${d.getFullYear()}-${mm}-${dd}`;
  }

  async function fetchIncomeStatusForProject(prjNo, startDateHyphen) {
    const body =
      "_JSON_=" +
      encodeURIComponent(
        JSON.stringify({
          START_DATE: startDateHyphen || "2020-01-01",
          END_DATE: todayHyphen(),
          PRJ_NO: prjNo,
          RES_CD: "",
        })
      );

    try {
      const res = await origFetch(INCOME_STATUS_URL, {
        method: "POST",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        },
        body,
        credentials: "include",
      });
      const data = await res.json();
      const rec = data && data.REC ? data.REC.map(normalizeKeys) : [];
      return rec;
    } catch (err) {
      console.log(`[WorkManager] 수입결의 조회 실패 (${prjNo}):`, err);
      return null; // 실패는 null로 구분 (0건과 다르게 취급)
    }
  }

  async function collectIncomeStatus(projects) {
    console.log(`[WorkManager] 수입결의 상태 조회 시작 - 총 ${projects.length}건`);
    const result = {};

    for (let i = 0; i < projects.length; i++) {
      const { 과제번호: prjNo, 시작일: startDate } = projects[i];
      if (!prjNo) continue;

      const rec = await fetchIncomeStatusForProject(prjNo, toHyphenDate(startDate));
      result[prjNo] = {
        건수: rec === null ? null : rec.length,
        총액: rec === null ? null : rec.reduce((sum, r) => sum + Number(r.REQ_AMT || 0), 0),
        상세: rec,
      };

      console.log(
        `[WorkManager] (${i + 1}/${projects.length}) ${prjNo} → ${
          rec === null ? "조회실패" : rec.length + "건"
        }`
      );

      if (i < projects.length - 1) await sleep(DELAY_MS);
    }

    console.log("[WorkManager] 수입결의 상태 조회 완료");
    window.postMessage(
      {
        source: "workmanager-inject",
        type: "INCOME_STATUS_RESULT",
        payload: result,
      },
      "*"
    );
  }

  // content.js로부터 조회 시작 요청을 받으면 실행
  window.addEventListener("message", (event) => {
    if (event.source !== window) return;
    if (!event.data || event.data.source !== "workmanager-content") return;

    if (event.data.type === "FETCH_INCOME_STATUS") {
      collectIncomeStatus(event.data.payload || []);
    }

    if (event.data.type === "FETCH_FUND_STATUS") {
      collectFundStatus(event.data.payload || []);
    }

    if (event.data.type === "FETCH_PROJECT_TYPE") {
      collectProjectDetail(event.data.payload || []);
    }
  });

  // -------------------------------------------------------------------
  // 자금현황 능동 조회
  // - 과제별 입금잔액(INQ_RCV_BAL_AMT)을 확인해서 "수입결의 필요 여부" 판정
  //   입금잔액 > 0 이면 돈은 들어왔는데 아직 수입결의 처리가 안 된 상태
  // -------------------------------------------------------------------
  const FUND_STATUS_URL = "/rcomm_0041_01_r002.jct";

  async function fetchFundStatusForProject(prjNo) {
    const body =
      "_JSON_=" +
      encodeURIComponent(
        JSON.stringify({
          USEFAC_SEQ_NO: "10",
          PRJ_NO: prjNo,
          RES_CD: "",
          INCLUDE_TAX: "Y",
        })
      );

    try {
      const res = await origFetch(FUND_STATUS_URL, {
        method: "POST",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        },
        body,
        credentials: "include",
      });
      const raw = await res.json();
      return raw ? normalizeKeys(raw) : null;
    } catch (err) {
      console.log(`[WorkManager] 자금현황 조회 실패 (${prjNo}):`, err);
      return null;
    }
  }

  async function collectFundStatus(projects) {
    console.log(`[WorkManager] 자금현황 조회 시작 - 총 ${projects.length}건`);
    const result = {};

    for (let i = 0; i < projects.length; i++) {
      const { 과제번호: prjNo } = projects[i];
      if (!prjNo) continue;

      const data = await fetchFundStatusForProject(prjNo);

      if (data === null) {
        result[prjNo] = { 조회실패: true };
      } else {
        result[prjNo] = {
          입금잔액: Number(data.INQ_RCV_BAL_AMT || 0),
          협약액: Number(data.INQ_ORG_SUP_AMT || 0),
          입금액: Number(data.INQ_RCV_AMT || 0),
          청구가능액: Number(data.INQ_REQ_POSS_AMT || 0),
          미승인액: Number(data.INQ_REQ_BAL_AMT || 0),
        };
      }

      console.log(
        `[WorkManager] (${i + 1}/${projects.length}) ${prjNo} → 입금잔액 ${
          data ? Number(data.INQ_RCV_BAL_AMT || 0).toLocaleString() : "조회실패"
        }`
      );

      if (i < projects.length - 1) await sleep(DELAY_MS);
    }

    console.log("[WorkManager] 자금현황 조회 완료");
    window.postMessage(
      {
        source: "workmanager-inject",
        type: "FUND_STATUS_RESULT",
        payload: result,
      },
      "*"
    );
  }

  // -------------------------------------------------------------------
  // 과제구분(수익과제/목적과제) 능동 조회
  // - 과제정보 상세조회 API의 ACCT_UNIT_NM 값으로 판정
  //   예: "글로벌_수익" → 수익과제, "일반_목적" → 목적과제
  // -------------------------------------------------------------------
  const PROJECT_DETAIL_URL = "/rtask_0008_t01_01_r001.jct";

  function classifyProjectType(acctUnitNm) {
    if (!acctUnitNm) return "-";
    if (acctUnitNm.includes("수익")) return "수익";
    if (acctUnitNm.includes("목적")) return "목적";
    return "-";
  }

  async function fetchProjectDetailForProject(prjNo) {
    const body =
      "_JSON_=" +
      encodeURIComponent(
        JSON.stringify({
          PRJ_NO: prjNo,
          USEFAC_SEQ_NO: "10",
        })
      );

    try {
      const res = await origFetch(PROJECT_DETAIL_URL, {
        method: "POST",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        },
        body,
        credentials: "include",
      });
      const raw = await res.json();
      return raw ? normalizeKeys(raw) : null;
    } catch (err) {
      console.log(`[WorkManager] 과제정보 조회 실패 (${prjNo}):`, err);
      return null;
    }
  }

  async function collectProjectDetail(projects) {
    console.log(`[WorkManager] 과제구분 조회 시작 - 총 ${projects.length}건`);
    const result = {};

    for (let i = 0; i < projects.length; i++) {
      const { 과제번호: prjNo } = projects[i];
      if (!prjNo) continue;

      const data = await fetchProjectDetailForProject(prjNo);

      if (data === null) {
        result[prjNo] = { 조회실패: true };
      } else {
        result[prjNo] = {
          구분: classifyProjectType(data.ACCT_UNIT_NM),
          계정단위명: data.ACCT_UNIT_NM || "",
        };
      }

      console.log(
        `[WorkManager] (${i + 1}/${projects.length}) ${prjNo} → ${
          data ? classifyProjectType(data.ACCT_UNIT_NM) : "조회실패"
        }`
      );

      if (i < projects.length - 1) await sleep(DELAY_MS);
    }

    console.log("[WorkManager] 과제구분 조회 완료");
    window.postMessage(
      {
        source: "workmanager-inject",
        type: "PROJECT_TYPE_RESULT",
        payload: result,
      },
      "*"
    );
  }
})();