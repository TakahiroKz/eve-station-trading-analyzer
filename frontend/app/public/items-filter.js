// Progressive enhancement for /items: the search box is hidden in the HTML and only shown
// here, so without JavaScript the page is a plain list of links. External file because the
// CSP does not allow inline scripts.
(function () {
  var input = document.getElementById("q");
  if (!input) return;
  var cards = Array.prototype.slice.call(document.querySelectorAll(".cat .card"));
  var sections = Array.prototype.slice.call(document.querySelectorAll("section.cat"));
  var empty = document.getElementById("empty");
  input.hidden = false;
  input.addEventListener("input", function () {
    var query = input.value.trim().toLowerCase();
    var shown = 0;
    cards.forEach(function (card) {
      var match = !query || card.getAttribute("data-n").indexOf(query) !== -1;
      card.parentNode.hidden = !match;
      if (match) shown += 1;
    });
    sections.forEach(function (section) {
      section.hidden = !section.querySelector("li:not([hidden])");
    });
    if (empty) empty.hidden = shown > 0;
  });
})();
