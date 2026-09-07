// content.js - isolated world (chrome.* API 사용 가능)
// 역할: inject.js가 postMessage로 보낸 과제 목록 데이터를 받아서
//       "내 이름"으로 필터링 후 storage에 "임시 저장"만 해둔다.
//       실제 파일 다운로드는 popup에서 사용자가 버튼을 눌러야 실행됨.

console.log("=================================");
console.log("WorkManager Extension 시작");
console.log("현재 페이지:", location.href);
console.log("=================================");

window.addEventListener("message", (event) => {
  if (event.source !== window) return;
  if (!event.data || event.data.source !== "workmanager-inject") return;
  if (event.data.type !== "PROJECT_LIST_DATA") return;

  const data = event.data.payload;

  // 임시 테스트용 - storage 없이 바로 이름 하드코딩
  // (팝업 UI로 실제 이름 저장하게 되면 아래 줄 대신
  //  chrome.storage.local.get(["workmanager_userName"], (result) => {...}) 으로 되돌리세요)
  const myName = "이효진";

  if (!myName) {
    console.log(
      "[WorkManager] 이름이 설정되지 않았습니다. 확장 아이콘을 눌러 이름을 입력해주세요."
    );
    return;
  }

  const myProjects = data.REC.filter((p) => p.PRJ_CHRG_GRP_NM === myName);

  console.log(`[WorkManager] "${myName}" 담당 과제 ${myProjects.length}건 감지됨`);

  // 감지될 때마다 파일로 즉시 저장하지 않고,
  // "이번에 감지된 결과 중 가장 건수가 많은 것"만 storage에 보관.
  // (500건 잘림 목록에서 잡힌 2건보다, 검색으로 잡힌 40건이 더 신뢰도 높은 결과이므로
  //  더 적은 건수로는 기존 저장값을 덮어쓰지 않는다)
  chrome.storage.local.get(["workmanager_cachedProjects"], (result) => {
    const cached = result.workmanager_cachedProjects;
    const cachedCount = cached ? cached.projects.length : -1;

    if (myProjects.length <= cachedCount) {
      console.log(
        `[WorkManager] 기존 캐시(${cachedCount}건)보다 적거나 같아 무시함`
      );
      return;
    }

    const simplified = myProjects.map((p) => ({
      과제번호: p.PRJ_NO,
      과제명: p.PRJ_NM,
      연구책임자: p.PRJ_RSPR_EMP_NM,
      담당자: p.PRJ_CHRG_GRP_NM,
      시작일: p.RCH_ST_DT,
      종료일: p.RCH_END_DT,
      지원기관: p.SUP_ORG_NM,
      총사업비: p.TOT_CASH_AMT,
      청구가능액: p.INQ_REQ_POSS_AMT,
    }));

    chrome.storage.local.set(
      {
        workmanager_cachedProjects: {
          projects: simplified,
          updatedAt: new Date().toISOString(),
          userName: myName,
        },
      },
      () => {
        console.log(
          `[WorkManager] 캐시 갱신됨: ${simplified.length}건 (팝업에서 내보내기 가능)`
        );
      }
    );
  });
});