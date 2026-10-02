// Проверка на преводите по език: един носител на език на всеки от 17-те,
// през ARB, iOS purpose strings, грешките от бекенда, правните текстове и
// описанията за магазините; след това адверсариална проверка на всяко
// твърдение. Пуснат за пръв път на 02.10.2026 по молба на Ив; намери
// `unknown_host` на английски в 16 езика, разнобой „ти/Вие" в онбординга на
// френски и чешки, и 104 потвърдени находки общо.
//
// Механичният слой (липсващи ключове, твърд текст, покритие на файловете) е
// отделно и е евтин: `python3 tools/i18n_audit.py <репо>`. Пускай първо него.
//
//     Workflow({name: 'translation-completeness'})
//
// Преди пускане: `tools/i18n_audit.py --json` за кандидатите по език, които
// скриптът очаква в scratchpad/lang/<език>.json.

export const meta = {
  name: 'translation-completeness',
  description: 'Пълнота на превода по език: ARB кандидати, purpose strings, правни текстове, грешки от сървъра, описания',
  phases: [
    { title: 'По език', detail: 'един проверяващ на всеки от 17-те езика, през всички повърхности' },
    { title: 'Потвърждение', detail: 'адверсариална проверка на твърденията за непреведено' },
  ],
}

const LANGS = [
  ['bg', 'български'], ['cs', 'чешки'], ['da', 'датски'], ['de', 'немски'], ['el', 'гръцки'],
  ['es', 'испански'], ['fr', 'френски'], ['hu', 'унгарски'], ['it', 'италиански'], ['ja', 'японски'],
  ['ko', 'корейски'], ['nb', 'норвежки'], ['nl', 'нидерландски'], ['pl', 'полски'], ['pt', 'португалски'],
  ['ro', 'румънски'], ['sv', 'шведски'],
]

const FINDINGS = {
  type: 'object',
  properties: {
    lang: { type: 'string' },
    verdict: { type: 'string', enum: ['пълен', 'дребни пропуски', 'сериозни пропуски'] },
    summary: { type: 'string', description: 'Едно изречение: какво е състоянието на този език' },
    issues: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          where: { type: 'string', description: 'Файл и ключ/ред, точно' },
          app: { type: 'string', enum: ['Beagle Owner', 'Dog Journey', 'и двете', 'бекенд'] },
          what: { type: 'string', description: 'Какво не е наред, с текста както стои сега' },
          should_be: { type: 'string', description: 'Правилният превод на този език' },
          severity: { type: 'string', enum: ['висока', 'средна', 'ниска'] },
          why_not_ok: { type: 'string', description: 'Защо това НЕ е легитимно изключение (име, бренд, международна дума)' },
        },
        required: ['where', 'app', 'what', 'should_be', 'severity', 'why_not_ok'],
      },
    },
    legitimate: { type: 'array', items: { type: 'string' }, description: 'Ключове, които съвпадат с английския законно — изброй ги, за да се види, че са прегледани' },
  },
  required: ['lang', 'verdict', 'summary', 'issues', 'legitimate'],
}

const VERDICT = {
  type: 'object',
  properties: {
    refuted: { type: 'boolean' },
    why: { type: 'string' },
  },
  required: ['refuted', 'why'],
}

const SCRATCH = '/tmp/claude-501/-Users-iv-Documents-Development-Business-Partner/7b407c0b-b664-4959-a097-9677e3e31abe/scratchpad/lang'
const BO = '/Users/iv/Documents/Development/MyBeagle'
const DJ = '/Users/iv/Documents/Development/AnotherDogApp'
const API = '/Users/iv/Documents/Development/MyBeagleApi'

function prompt(code, name) {
  return [
    'Ти си носител на ' + name + ' език и проверяваш превода на две мобилни приложения.',
    '',
    'Въпросът на собственика е точен: има ли език, на който преводът не е пълен, или',
    'секция, която не е преведена на съответния език. Твоят език е ' + code + ' (' + name + ').',
    '',
    'ПОВЪРХНОСТИ ЗА ПРОВЕРКА — всички, не само първата:',
    '',
    '1. ' + SCRATCH + '/' + code + '.json — вече извлечени кандидати: низове, чийто превод е',
    '   дума по дума същият като английския. Част от тях са законни (име на приложението,',
    '   "Plus", "OK", "Email", международни думи, които на твоя език наистина са същите).',
    '   Другите са непреведени. Раздели ги.',
    '',
    '2. ARB файловете — отвори ги и прегледай превода като цяло, не само кандидатите:',
    '   - Beagle Owner: ' + BO + '/lib/l10n/app_' + code + '.arb',
    '   - Dog Journey: ' + DJ + '/apps/universal/lib/l10n/app_' + code + '.arb',
    '   Търси и: полуфразов превод (половината изречение на английски), смесена',
    '   терминология (един и същ термин преведен различно на два екрана), машинен',
    '   буквализъм, който на твоя език не значи нищо, непоследователна учтива форма,',
    '   текст, който очевидно е от друго приложение.',
    '',
    '3. Текстовете за разрешенията на iOS (показват се в системен диалог):',
    '   - ' + BO + '/ios/Runner/' + code + '.lproj/InfoPlist.strings',
    '   - ' + DJ + '/apps/universal/ios/Runner/' + code + '.lproj/InfoPlist.strings',
    '',
    '4. Грешките, които сървърът връща на този език:',
    '   ' + API + '/app/core/error_texts.py — блокът за "' + code + '".',
    '',
    '5. Правните текстове (дълги; търси недовършен или английски абзац):',
    '   - ' + API + '/app/modules/legal/docs/beagle/terms.' + code + '.md',
    '   - ' + API + '/app/modules/legal/docs/beagle/privacy.' + code + '.md',
    '   - ' + API + '/app/modules/legal/docs/dogjourney/terms.' + code + '.md',
    '   - ' + API + '/app/modules/legal/docs/dogjourney/privacy.' + code + '.md',
    '',
    '6. Описанието за магазините (Dog Journey):',
    '   ' + DJ + '/apps/universal/tool/store_text/' + code + '.json',
    '',
    'ПРАВИЛА:',
    '- Само ЧЕТЕНЕ. Не редактирай нито един файл, не пускай git, билд или тестове.',
    '- За всяко твърдение дай точно място (файл + ключ или ред) и текста както стои сега.',
    '- Давай и правилния превод — той ще влезе в поправката.',
    '- Не раздувай: "OK", "Email", "Plus", имена на приложения и породи, "QR" и подобни',
    '  НЕ са дефекти. Изброй ги в legitimate, за да личи, че са прегледани.',
    '- Дребен стилов спор не е дефект. Дефект е: английски текст пред потребител на',
    '  твоя език, полупреведено изречение, несъществуваща на твоя език дума, объркан',
    '  смисъл, учтива форма, различна от останалата част на същия файл.',
    '- Отговаряй на български (докладът е за собственика), цитатите — на оригиналния език.',
  ].join('\n')
}

phase('По език')

const perLang = await parallel(
  LANGS.map(([code, name]) => () =>
    agent(prompt(code, name), { label: code + ' (' + name + ')', phase: 'По език', schema: FINDINGS })
  )
)

const found = perLang.filter(Boolean)
const issues = found.flatMap((r) => (r.issues || []).map((i) => ({ ...i, lang: r.lang })))
log('Проверени ' + found.length + ' езика · ' + issues.length + ' твърдения за непреведено')

const toVerify = issues.filter((i) => i.severity !== 'ниска')
log('Адверсариална проверка на ' + toVerify.length + ' (ниските ' + (issues.length - toVerify.length) + ' минават без нея)')

phase('Потвърждение')

const checked = await parallel(
  toVerify.map((i) => () =>
    agent(
      [
        'Опитай се да ОБОРИШ това твърдение за непълен превод. По подразбиране приемай,',
        'че твърдението е невярно, освен ако не го потвърдиш сам.',
        '',
        'Език: ' + i.lang,
        'Къде: ' + i.where + ' (' + i.app + ')',
        'Твърди се: ' + i.what,
        'Предложен превод: ' + i.should_be,
        'Защо се твърди, че не е законно изключение: ' + i.why_not_ok,
        '',
        'Отвори файла и провери сам. Твърдението е ОБОРЕНО, ако:',
        '- текстът всъщност е преведен (проверяващият е гледал друг ключ или друг файл);',
        '- съвпадението с английския е законно на този език (международна дума, име,',
        '  бренд, "OK", термин, който на този език наистина се пише така);',
        '- мястото не се показва на потребител (коментар, неизползван ключ, тестов файл).',
        '',
        'Само ЧЕТЕНЕ, никакви промени. Отговаряй на български.',
      ].join('\n'),
      { label: i.lang + ': ' + i.where.slice(0, 32), phase: 'Потвърждение', schema: VERDICT, effort: 'high' }
    ).then((v) => ({ ...i, verdict: v }))
  )
)

const confirmed = checked.filter(Boolean).filter((i) => i.verdict && !i.verdict.refuted)
const rejected = checked.filter(Boolean).filter((i) => i.verdict && i.verdict.refuted)

return {
  по_езици: found.map((r) => ({ език: r.lang, оценка: r.verdict, обобщение: r.summary, брой: (r.issues || []).length })),
  потвърдени: confirmed.map((i) => ({
    език: i.lang, приложение: i.app, място: i.where, сега: i.what,
    трябва: i.should_be, тежест: i.severity, проверка: i.verdict.why,
  })),
  оборени: rejected.map((i) => ({ език: i.lang, място: i.where, защо_отпада: i.verdict.why })),
  ниски: issues.filter((i) => i.severity === 'ниска').map((i) => ({ език: i.lang, място: i.where, сега: i.what, трябва: i.should_be })),
}
