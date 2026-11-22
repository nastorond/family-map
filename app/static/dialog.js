(function () {
  "use strict";
  var dialog = document.getElementById("add-dialog");
  if (!dialog) return;

  // 팝업 본문에 내용이 들어오면 연다.
  document.body.addEventListener("htmx:afterSwap", function (e) {
    if (e.detail.target && e.detail.target.id === "add-dialog-body" && !dialog.open) {
      dialog.showModal();
    }
  });

  dialog.addEventListener("click", function (e) {
    // 닫기 버튼, 또는 팝업 바깥(배경) 클릭
    if (e.target.closest("[data-close-dialog]") || e.target === dialog) dialog.close();
  });

  // 불러오기 실패하면 전체 페이지로 이동
  document.body.addEventListener("htmx:responseError", function (e) {
    var path = e.detail.pathInfo && e.detail.pathInfo.requestPath;
    if (path) location.href = path;
  });
})();
