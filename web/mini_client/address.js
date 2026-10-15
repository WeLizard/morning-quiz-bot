// Account-level form of address (он / она / не указывать). Mirror of domain/address.py.
// Telegram does not report gender, so nothing here guesses it: unknown means neutral.
// A classic script and an ES-module side-effect import both expose globalThis.QWAddress.
(function (root) {
  'use strict';
  var FORMS = ['m', 'f', 'n'];
  var LABELS = {m: 'он', f: 'она', n: 'не указывать'};
  function effective(form) { return FORMS.indexOf(form) >= 0 ? form : 'n'; }
  // g(form, 'собрал', 'собрала', 'собрано'): the third wording must be truly neutral, not "собрал(а)".
  function g(form, masculine, feminine, neutral) {
    var f = effective(form);
    return f === 'm' ? masculine : f === 'f' ? feminine : neutral;
  }
  root.QWAddress = Object.freeze({FORMS: FORMS, LABELS: LABELS, effective: effective, g: g});
})(typeof globalThis !== 'undefined' ? globalThis : window);
