// inject.js - MAIN world (페이지와 같은 JS 컨텍스트에서 실행됨)
// 역할: 페이지가 서버에 보내는 fetch/XHR 요청 중 과제 목록 API(rmain_0003_01_l001.jct) 응답을 가로채서
//       content.js(isolated world)로 postMessage 전달

(function () {
  console.log("[WorkManager] inject.js 로드됨 (MAIN world)");

  // 이 ERP는 일부 필드 키에 한글 설명이 괄호로 붙어서 내려옴
  // 예: "INQ_RCV_BAL_AMT(입금잔액)" - 심지어 같은 배열/과제 안에서도
  // 붙었다 안 붙었다 들쭉날쭉해서, 라벨 텍스트로 찾는 방식은 신뢰할 수 없음.
  // 항상 괄호 앞부분(고정 필드명)만 잘라서 키를 통일시켜 읽어야 함.
  function normalizeKeys(obj) {
    if (!obj || typeof obj !== "object") return obj;
    const result = {};
    for (const key in obj) {
      const baseKey = key.split("(")[0].trim();
      result[key] = obj[key];
      result[baseKey] = obj[key];
    }
    return result;
  }

  function parseAmount(value) {
    if (value === null || value === undefined || value === "") return 0;
    if (typeof value === "number") return Number.isFinite(value) ? value : 0;

    const parsed = Number(String(value).replace(/,/g, "").trim());
    return Number.isFinite(parsed) ? parsed : 0;
  }

  // 자금현황 API(rcomm_0041_01_r002.jct) 응답은 평면 객체(REC 배열 아님).
  // 고정 필드명(INQ_AGRMT_AMT, INQ_RCV_AMT, INQ_TAX_AMT)을 직접 읽어서 계산.
  // 청구가능액 = 협약액 - (입금액공급가액 + 입금액부가세)
  function calculateClaimableAmount(rawData) {
    const data = normalizeKeys(rawData);

    if (!("INQ_AGRMT_AMT" in data)) return null;

    const agreement = parseAmount(data.INQ_AGRMT_AMT);
    const receivedSupply = parseAmount(data.INQ_RCV_AMT);
    const receivedVat = parseAmount(data.INQ_TAX_AMT);

    return {
      협약액: agreement,
      입금액공급가액: receivedSupply,
      입금액부가세: receivedVat,
      청구가능액: agreement - (receivedSupply + receivedVat),
    };
  }

  // 타겟 API 파일명 - 과제 목록을 내려주는 요청
  const TARGET_URL_PATTERN = /rmain_0003_01_l001/;
  // 예산잔액이 포함된 과제 목록 요청 (자금현황 개별조회 대신 이걸로 한 번에 확보)
  const BUDGET_LIST_PATTERN = /rmain_0005_01_r001/;

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

  function sendBudgetData(data) {
    window.postMessage(
      {
        source: "workmanager-inject",
        type: "BUDGET_LIST_DATA",
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

    if (BUDGET_LIST_PATTERN.test(url)) {
      res
        .clone()
        .json()
        .then((data) => {
          if (data && data.REC) {
            console.log("[WorkManager] 예산잔액 목록 응답 감지(fetch):", url);
            sendBudgetData(data);
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

      if (BUDGET_LIST_PATTERN.test(url)) {
        try {
          const data = JSON.parse(this.responseText);
          if (data && data.REC) {
            console.log("[WorkManager] 예산잔액 목록 응답 감지(XHR):", url);
            sendBudgetData(data);
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

  // content.js로부터 오는 메시지 + 과제 목록 자체 감지 후 자동 트리거
  window.addEventListener("message", (event) => {
    if (event.source !== window) return;
    if (!event.data || event.data.source !== "workmanager-content") return;

    if (event.data.type === "FETCH_INCOME_STATUS") {
      collectIncomeStatus(event.data.payload || []);
    }

    if (event.data.type === "FETCH_PROJECT_TYPE") {
      collectProjectDetail(event.data.payload || []);
    }

    if (event.data.type === "FETCH_CLAIMABLE_AMOUNT") {
      collectClaimableAmount(event.data.payload || []);
    }
  });

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

  // -------------------------------------------------------------------
  // 청구가능액 능동 조회/계산
  // - 자금현황 API(rcomm_0041_01_r002.jct) 응답을 그대로 쓰지 않고
  //   협약액 - (입금액공급가액 + 입금액부가세) 로 직접 계산
  // -------------------------------------------------------------------
  const CLAIMABLE_URL = "/rcomm_0041_01_r002.jct";

  async function fetchClaimableForProject(prjNo) {
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
      const res = await origFetch(CLAIMABLE_URL, {
        method: "POST",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        },
        body,
        credentials: "include",
      });

      if (!res.ok) {
        const text = await res.text().catch(() => "");
        console.log(
          `[WorkManager] 청구가능액 HTTP 오류 (${prjNo}): status=${res.status} body=${text.slice(0, 200)}`
        );
        return null;
      }

      const raw = await res.json();
      const result = calculateClaimableAmount(raw);
      if (!result) {
        console.log(`[WorkManager] 청구가능액 필드 없음 (${prjNo}):`, raw);
      }
      return result;
    } catch (err) {
      console.log(`[WorkManager] 청구가능액 조회 예외 (${prjNo}):`, err);
      return null;
    }
  }

  async function collectClaimableAmount(projects) {
    console.log(`[WorkManager] 청구가능액 조회 시작 - 총 ${projects.length}건`);
    const result = {};

    for (let i = 0; i < projects.length; i++) {
      const { 과제번호: prjNo } = projects[i];
      if (!prjNo) continue;

      const data = await fetchClaimableForProject(prjNo);

      if (data === null) {
        result[prjNo] = null; // 조회 실패
      } else {
        result[prjNo] = data;
      }

      console.log(
        `[WorkManager] (${i + 1}/${projects.length}) ${prjNo} → 청구가능액 ${
          result[prjNo] === null ? "조회실패" : result[prjNo].청구가능액.toLocaleString()
        }`
      );

      if (i < projects.length - 1) await sleep(DELAY_MS);
    }

    console.log("[WorkManager] 청구가능액 조회 완료");
    window.postMessage(
      {
        source: "workmanager-inject",
        type: "CLAIMABLE_RESULT",
        payload: result,
      },
      "*"
    );
  }

  if (window.__WORKMANAGER_TEST__) {
    window.__workmanagerTest = {
      normalizeKeys,
      calculateClaimableAmount,
    };
  }
})();