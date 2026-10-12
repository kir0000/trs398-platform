// Russian formatting for the charts: decimal comma, dd.mm.yyyy dates, Russian month and day names.
// Loaded after plotly.min.js on Russian pages only (English pages keep the built-in locale).
(function () {
  if (!window.Plotly) return;
  Plotly.register({
    moduleType: 'locale', name: 'ru', dictionary: {},
    format: {
      decimal: ',', thousands: ' ', grouping: [3], currency: ['', ' ₽'],
      dateTime: '%d.%m.%Y %X', date: '%d.%m.%Y', time: '%H:%M:%S', periods: ['AM', 'PM'],
      days: ['Воскресенье', 'Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота'],
      shortDays: ['Вс', 'Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб'],
      months: ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь'],
      shortMonths: ['янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']
    }
  });
  Plotly.setPlotConfig({locale: 'ru'});
})();
