(function () {
  "use strict";
  var input = document.getElementById("pick-search");
  var items = Array.prototype.slice.call(document.querySelectorAll("#pick-list .pick"));
  var empty = document.getElementById("pick-empty");
  if (!input) return;

  input.addEventListener("input", function () {
    var q = input.value.trim().replace(/\s+/g, "");
    var shown = 0;
    items.forEach(function (li) {
      var hit = !q || li.dataset.search.replace(/\s+/g, "").indexOf(q) !== -1;
      li.hidden = !hit;
      if (hit) shown++;
    });
    empty.hidden = shown !== 0;
  });
})();
