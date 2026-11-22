(function () {
  "use strict";

  var el = document.getElementById("FamilyChart");
  if (!el || !window.f3) return;

  // family-chart는 카드 문구를 innerHTML로 넣으므로 여기서 이스케이프한다.
  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  var nameEl = document.getElementById("tree-main-name");
  var linkEl = document.getElementById("tree-main-link");
  var personUrl = el.dataset.personUrl;

  fetch(el.dataset.src, { credentials: "same-origin", headers: { Accept: "application/json" } })
    .then(function (res) {
      if (!res.ok) throw new Error("HTTP " + res.status);
      return res.json();
    })
    .then(function (people) {
      var chart = f3.createChart("#FamilyChart", people)
        .setTransitionTime(600)
        .setCardXSpacing(150)
        .setCardYSpacing(110)
        .setSingleParentEmptyCard(false)
        .setShowSiblingsOfMain(true);

      chart.setCardHtml()
        .setStyle("rect")
        .setMiniTree(true)
        .setCardDisplay([
          function (d) {
            return esc(d.data.name) + (d.data.deceased ? ' <span class="deceased">(고인)</span>' : "");
          },
          function (d) {
            var parts = [d.data.title, d.data.birth].filter(Boolean);
            return esc(parts.join(" · "));
          },
        ])
        .setOnCardUpdate(function (d) {
          var card = this.querySelector(".card");
          if (card && d.data.data.gender_unknown) card.classList.add("card-gender-unknown");
        });

      chart.setAfterUpdate(function () {
        var main = chart.getMainDatum();
        if (!main) return;
        nameEl.textContent = main.data.name;
        linkEl.href = personUrl + main.id;
        var url = main.id === el.dataset.me ? location.pathname : location.pathname + "?main=" + main.id;
        history.replaceState(null, "", url);
      });

      chart.updateMainId(el.dataset.main);
      chart.updateTree({ initial: true });
    })
    .catch(function () {
      el.innerHTML = '<p class="tree-error">가계도를 불러오지 못했어요. 새로고침해 주세요.</p>';
    });
})();
