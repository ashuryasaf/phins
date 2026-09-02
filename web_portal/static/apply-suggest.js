/* Shared apply-form typeahead: phone country codes, countries/cities,
 * occupations, and medications. Used by apply.html and apply-chat.html.
 * Suggestions assist typing; free text is still accepted so unusual
 * values are not lost.
 */
(function (global) {
    'use strict';

    const DIAL_CODES = [
        { iso: 'IL', name: 'Israel', dial: '972' },
        { iso: 'US', name: 'United States', dial: '1' },
        { iso: 'GB', name: 'United Kingdom', dial: '44' },
        { iso: 'CA', name: 'Canada', dial: '1' },
        { iso: 'AU', name: 'Australia', dial: '61' },
        { iso: 'DE', name: 'Germany', dial: '49' },
        { iso: 'FR', name: 'France', dial: '33' },
        { iso: 'IT', name: 'Italy', dial: '39' },
        { iso: 'ES', name: 'Spain', dial: '34' },
        { iso: 'NL', name: 'Netherlands', dial: '31' },
        { iso: 'BE', name: 'Belgium', dial: '32' },
        { iso: 'CH', name: 'Switzerland', dial: '41' },
        { iso: 'AT', name: 'Austria', dial: '43' },
        { iso: 'SE', name: 'Sweden', dial: '46' },
        { iso: 'NO', name: 'Norway', dial: '47' },
        { iso: 'DK', name: 'Denmark', dial: '45' },
        { iso: 'FI', name: 'Finland', dial: '358' },
        { iso: 'IE', name: 'Ireland', dial: '353' },
        { iso: 'PT', name: 'Portugal', dial: '351' },
        { iso: 'GR', name: 'Greece', dial: '30' },
        { iso: 'PL', name: 'Poland', dial: '48' },
        { iso: 'CZ', name: 'Czechia', dial: '420' },
        { iso: 'HU', name: 'Hungary', dial: '36' },
        { iso: 'RO', name: 'Romania', dial: '40' },
        { iso: 'BG', name: 'Bulgaria', dial: '359' },
        { iso: 'HR', name: 'Croatia', dial: '385' },
        { iso: 'RS', name: 'Serbia', dial: '381' },
        { iso: 'UA', name: 'Ukraine', dial: '380' },
        { iso: 'RU', name: 'Russia', dial: '7' },
        { iso: 'TR', name: 'Turkey', dial: '90' },
        { iso: 'CY', name: 'Cyprus', dial: '357' },
        { iso: 'JO', name: 'Jordan', dial: '962' },
        { iso: 'LB', name: 'Lebanon', dial: '961' },
        { iso: 'EG', name: 'Egypt', dial: '20' },
        { iso: 'AE', name: 'United Arab Emirates', dial: '971' },
        { iso: 'SA', name: 'Saudi Arabia', dial: '966' },
        { iso: 'QA', name: 'Qatar', dial: '974' },
        { iso: 'KW', name: 'Kuwait', dial: '965' },
        { iso: 'BH', name: 'Bahrain', dial: '973' },
        { iso: 'OM', name: 'Oman', dial: '968' },
        { iso: 'MA', name: 'Morocco', dial: '212' },
        { iso: 'ZA', name: 'South Africa', dial: '27' },
        { iso: 'NG', name: 'Nigeria', dial: '234' },
        { iso: 'KE', name: 'Kenya', dial: '254' },
        { iso: 'IN', name: 'India', dial: '91' },
        { iso: 'PK', name: 'Pakistan', dial: '92' },
        { iso: 'BD', name: 'Bangladesh', dial: '880' },
        { iso: 'CN', name: 'China', dial: '86' },
        { iso: 'JP', name: 'Japan', dial: '81' },
        { iso: 'KR', name: 'South Korea', dial: '82' },
        { iso: 'SG', name: 'Singapore', dial: '65' },
        { iso: 'HK', name: 'Hong Kong', dial: '852' },
        { iso: 'TW', name: 'Taiwan', dial: '886' },
        { iso: 'TH', name: 'Thailand', dial: '66' },
        { iso: 'VN', name: 'Vietnam', dial: '84' },
        { iso: 'PH', name: 'Philippines', dial: '63' },
        { iso: 'ID', name: 'Indonesia', dial: '62' },
        { iso: 'MY', name: 'Malaysia', dial: '60' },
        { iso: 'NZ', name: 'New Zealand', dial: '64' },
        { iso: 'MX', name: 'Mexico', dial: '52' },
        { iso: 'BR', name: 'Brazil', dial: '55' },
        { iso: 'AR', name: 'Argentina', dial: '54' },
        { iso: 'CL', name: 'Chile', dial: '56' },
        { iso: 'CO', name: 'Colombia', dial: '57' },
        { iso: 'PE', name: 'Peru', dial: '51' },
    ];

    const CITIES = {
        'Israel': ['Tel Aviv', 'Jerusalem', 'Haifa', 'Rishon LeZion', 'Petah Tikva', 'Ashdod', 'Netanya', 'Beer Sheva', 'Holon', 'Bnei Brak', 'Ramat Gan', 'Rehovot', 'Herzliya', 'Kfar Saba', 'Modiin'],
        'United States': ['New York', 'Los Angeles', 'Chicago', 'Houston', 'Phoenix', 'Philadelphia', 'San Antonio', 'San Diego', 'Dallas', 'San Jose', 'Austin', 'Jacksonville', 'Miami', 'Seattle', 'Boston', 'Denver', 'Washington', 'Atlanta'],
        'United Kingdom': ['London', 'Manchester', 'Birmingham', 'Leeds', 'Glasgow', 'Liverpool', 'Edinburgh', 'Bristol', 'Sheffield', 'Newcastle', 'Cardiff', 'Belfast'],
        'Canada': ['Toronto', 'Montreal', 'Vancouver', 'Calgary', 'Ottawa', 'Edmonton', 'Quebec City', 'Winnipeg'],
        'Australia': ['Sydney', 'Melbourne', 'Brisbane', 'Perth', 'Adelaide', 'Canberra', 'Gold Coast'],
        'Germany': ['Berlin', 'Munich', 'Hamburg', 'Frankfurt', 'Cologne', 'Stuttgart', 'Dusseldorf'],
        'France': ['Paris', 'Lyon', 'Marseille', 'Toulouse', 'Nice', 'Nantes', 'Strasbourg'],
        'Italy': ['Rome', 'Milan', 'Naples', 'Turin', 'Florence', 'Bologna', 'Venice'],
        'Spain': ['Madrid', 'Barcelona', 'Valencia', 'Seville', 'Bilbao', 'Malaga'],
        'Netherlands': ['Amsterdam', 'Rotterdam', 'The Hague', 'Utrecht', 'Eindhoven'],
        'Belgium': ['Brussels', 'Antwerp', 'Ghent', 'Bruges', 'Liege'],
        'Switzerland': ['Zurich', 'Geneva', 'Basel', 'Bern', 'Lausanne'],
        'Austria': ['Vienna', 'Salzburg', 'Graz', 'Innsbruck'],
        'Sweden': ['Stockholm', 'Gothenburg', 'Malmo'],
        'Norway': ['Oslo', 'Bergen', 'Trondheim'],
        'Denmark': ['Copenhagen', 'Aarhus', 'Odense'],
        'Finland': ['Helsinki', 'Espoo', 'Tampere'],
        'Ireland': ['Dublin', 'Cork', 'Galway', 'Limerick'],
        'Portugal': ['Lisbon', 'Porto', 'Braga'],
        'Greece': ['Athens', 'Thessaloniki', 'Patras'],
        'Poland': ['Warsaw', 'Krakow', 'Gdansk', 'Wroclaw'],
        'Turkey': ['Istanbul', 'Ankara', 'Izmir', 'Antalya'],
        'United Arab Emirates': ['Dubai', 'Abu Dhabi', 'Sharjah', 'Ajman'],
        'Saudi Arabia': ['Riyadh', 'Jeddah', 'Dammam', 'Mecca'],
        'Egypt': ['Cairo', 'Alexandria', 'Giza'],
        'Jordan': ['Amman', 'Irbid', 'Zarqa', 'Aqaba'],
        'India': ['Mumbai', 'Delhi', 'Bengaluru', 'Hyderabad', 'Chennai', 'Kolkata', 'Pune'],
        'China': ['Beijing', 'Shanghai', 'Shenzhen', 'Guangzhou', 'Chengdu'],
        'Japan': ['Tokyo', 'Osaka', 'Yokohama', 'Nagoya', 'Kyoto'],
        'South Korea': ['Seoul', 'Busan', 'Incheon'],
        'Singapore': ['Singapore'],
        'South Africa': ['Johannesburg', 'Cape Town', 'Durban', 'Pretoria'],
        'Brazil': ['Sao Paulo', 'Rio de Janeiro', 'Brasilia', 'Salvador'],
        'Mexico': ['Mexico City', 'Guadalajara', 'Monterrey', 'Cancun'],
        'New Zealand': ['Auckland', 'Wellington', 'Christchurch'],
    };

    const OCCUPATIONS = [
        'Accountant', 'Actuary', 'Administrative Assistant', 'Architect',
        'Artist', 'Attorney', 'Banker', 'Business Analyst', 'Business Owner',
        'Caregiver', 'Carpenter', 'Chef', 'Civil Engineer', 'Consultant',
        'Contractor', 'Customer Service Representative', 'Data Analyst',
        'Dentist', 'Designer', 'Developer', 'Doctor', 'Driver', 'Electrician',
        'Engineer', 'Entrepreneur', 'Financial Advisor', 'Firefighter',
        'Graphic Designer', 'Homemaker', 'Human Resources Manager',
        'Information Technology Specialist', 'Insurance Agent', 'Journalist',
        'Lawyer', 'Lecturer', 'Marketing Manager', 'Mechanic', 'Medical Assistant',
        'Military', 'Nurse', 'Office Manager', 'Paramedic', 'Pharmacist',
        'Physician', 'Pilot', 'Plumber', 'Police Officer', 'Product Manager',
        'Professor', 'Programmer', 'Project Manager', 'Real Estate Agent',
        'Researcher', 'Retired', 'Sales Manager', 'Scientist', 'Self-employed',
        'Social Worker', 'Software Engineer', 'Student', 'Teacher',
        'Technician', 'Therapist', 'Trader', 'Truck Driver', 'Unemployed',
        'Veterinarian', 'Writer',
    ];

    const MEDICATIONS = [
        'None', 'Aspirin', 'Atorvastatin', 'Lisinopril', 'Metformin',
        'Amlodipine', 'Metoprolol', 'Omeprazole', 'Losartan', 'Albuterol',
        'Gabapentin', 'Hydrochlorothiazide', 'Sertraline', 'Simvastatin',
        'Levothyroxine', 'Azithromycin', 'Amoxicillin', 'Ibuprofen',
        'Acetaminophen', 'Insulin', 'Warfarin', 'Clopidogrel', 'Furosemide',
        'Pantoprazole', 'Rosuvastatin', 'Escitalopram', 'Fluoxetine',
        'Citalopram', 'Trazodone', 'Prednisone', 'Montelukast', 'Cetirizine',
        'Loratadine', 'Ventolin', 'Symbicort', 'Advair', 'Eliquis',
        'Xarelto', 'Jardiance', 'Ozempic', 'Trulicity', 'Januvia',
        'Crestor', 'Lipitor', 'Norvasc', 'Zoloft', 'Prozac', 'Xanax',
        'Vitamin D', 'Vitamin B12', 'Omega-3', 'Iron supplement',
    ];

    const COUNTRIES = DIAL_CODES.map((row) => row.name)
        .filter((name, idx, all) => all.indexOf(name) === idx);

    function norm(value) {
        return String(value || '').trim().toLowerCase();
    }

    function digitsOnly(value) {
        return String(value || '').replace(/\D/g, '');
    }

    function defaultDial() {
        const lang = String(document.documentElement.lang || '').toLowerCase();
        return lang.startsWith('he') ? '972' : '1';
    }

    function composePhone(dial, national) {
        const parsed = parsePhone(String(national || '').trim());
        if (parsed.dial && parsed.national) {
            return '+' + parsed.dial + parsed.national;
        }
        let code = digitsOnly(dial);
        let local = digitsOnly(national);
        if (!code && parsed.dial) code = parsed.dial;
        if (local.startsWith('0')) local = local.slice(1);
        if (code && local.startsWith(code) && local.length > code.length + 6) {
            local = local.slice(code.length);
        }
        if (!code || !local) return '';
        return '+' + code + local;
    }

    function parsePhone(value) {
        const raw = String(value || '').trim();
        if (!raw) return { dial: '', national: '', e164: '' };
        const plus = raw.startsWith('+');
        const digits = digitsOnly(raw);
        if (plus || digits.length >= 10) {
            const matches = DIAL_CODES
                .filter((row) => digits.startsWith(row.dial))
                .sort((a, b) => b.dial.length - a.dial.length);
            if (matches.length) {
                const dial = matches[0].dial;
                let national = digits.slice(dial.length);
                if (national.startsWith('0')) national = national.slice(1);
                return { dial, national, e164: '+' + dial + national };
            }
        }
        return { dial: '', national: digits, e164: plus ? '+' + digits : digits };
    }

    function formatDial(row) {
        return '+' + row.dial + ' ' + row.name;
    }

    function matchQuery(hay, query) {
        if (!query) return true;
        return norm(hay).indexOf(query) !== -1;
    }

    function suggest(kind, query, opts) {
        const q = norm(query);
        const limit = (opts && opts.limit) || 8;
        if (kind === 'phone' || kind === 'dial') {
            const qDigits = digitsOnly(q);
            return DIAL_CODES.filter((row) => {
                return matchQuery(row.name, q)
                    || matchQuery(row.iso, q)
                    || ('+' + row.dial).indexOf(q.replace(/\s/g, '')) === 0
                    || (qDigits && row.dial.indexOf(qDigits) === 0);
            }).slice(0, limit).map((row) => ({
                value: '+' + row.dial,
                label: formatDial(row),
                meta: row,
            }));
        }
        if (kind === 'country') {
            return COUNTRIES.filter((name) => matchQuery(name, q))
                .slice(0, limit)
                .map((name) => ({ value: name, label: name }));
        }
        if (kind === 'city') {
            const country = (opts && opts.country) || '';
            const pool = [];
            if (country && CITIES[country]) {
                CITIES[country].forEach((city) => pool.push(city));
            } else {
                Object.keys(CITIES).forEach((c) => {
                    CITIES[c].forEach((city) => pool.push(city));
                });
            }
            return pool.filter((city, idx, all) => all.indexOf(city) === idx && matchQuery(city, q))
                .slice(0, limit)
                .map((city) => ({ value: city, label: city }));
        }
        if (kind === 'occupation') {
            return OCCUPATIONS.filter((job) => matchQuery(job, q))
                .slice(0, limit)
                .map((job) => ({ value: job, label: job }));
        }
        if (kind === 'medication') {
            const token = q.split(/[,;\n]/).pop().trim();
            return MEDICATIONS.filter((med) => matchQuery(med, token))
                .slice(0, limit)
                .map((med) => ({ value: med, label: med }));
        }
        return [];
    }

    function closeAll(except) {
        document.querySelectorAll('.phins-suggest-list').forEach((list) => {
            if (list !== except) list.hidden = true;
        });
    }

    function attach(input, options) {
        if (!input || input.dataset.phinsSuggestAttached === '1') return null;
        options = options || {};
        const kind = options.kind || 'text';
        input.dataset.phinsSuggestAttached = '1';
        input.setAttribute('autocomplete', 'off');
        input.setAttribute('role', 'combobox');
        input.setAttribute('aria-autocomplete', 'list');

        const wrap = document.createElement('div');
        wrap.className = 'phins-suggest';
        input.parentNode.insertBefore(wrap, input);
        wrap.appendChild(input);

        const list = document.createElement('ul');
        list.className = 'phins-suggest-list';
        list.hidden = true;
        list.setAttribute('role', 'listbox');
        wrap.appendChild(list);

        let active = -1;
        let items = [];

        function currentQuery() {
            if (kind === 'medication') {
                const parts = String(input.value || '').split(/[,;\n]/);
                return parts[parts.length - 1] || '';
            }
            return input.value;
        }

        function applyValue(item) {
            if (kind === 'medication') {
                const raw = String(input.value || '');
                const parts = raw.split(/[,;\n]/);
                parts[parts.length - 1] = (parts.length > 1 ? ' ' : '') + item.value;
                input.value = parts.join(',').replace(/^\s+/, '');
            } else if (kind === 'phone' || kind === 'dial') {
                input.value = item.label;
                input.dataset.dial = item.meta ? item.meta.dial : digitsOnly(item.value);
            } else {
                input.value = item.value;
            }
            list.hidden = true;
            active = -1;
            input.dispatchEvent(new Event('input', { bubbles: true }));
            input.dispatchEvent(new Event('change', { bubbles: true }));
            if (typeof options.onSelect === 'function') options.onSelect(item, input);
        }

        function paint() {
            const country = typeof options.getCountry === 'function'
                ? options.getCountry()
                : options.country;
            items = suggest(kind, currentQuery(), { country, limit: options.limit });
            list.innerHTML = '';
            if (!items.length) {
                list.hidden = true;
                return;
            }
            items.forEach((item, idx) => {
                const li = document.createElement('li');
                li.className = 'phins-suggest-item';
                li.setAttribute('role', 'option');
                li.textContent = item.label;
                if (idx === active) li.classList.add('active');
                li.addEventListener('mousedown', (event) => {
                    event.preventDefault();
                    applyValue(item);
                });
                list.appendChild(li);
            });
            list.hidden = false;
        }

        input.addEventListener('input', () => {
            active = -1;
            paint();
        });
        input.addEventListener('focus', () => {
            closeAll(list);
            paint();
        });
        input.addEventListener('blur', () => {
            setTimeout(() => { list.hidden = true; }, 120);
        });
        input.addEventListener('keydown', (event) => {
            if (list.hidden && (event.key === 'ArrowDown' || event.key === 'ArrowUp')) {
                paint();
            }
            if (list.hidden || !items.length) return;
            if (event.key === 'ArrowDown') {
                event.preventDefault();
                active = (active + 1) % items.length;
                paint();
            } else if (event.key === 'ArrowUp') {
                event.preventDefault();
                active = (active - 1 + items.length) % items.length;
                paint();
            } else if (event.key === 'Enter' && active >= 0) {
                event.preventDefault();
                applyValue(items[active]);
            } else if (event.key === 'Escape') {
                list.hidden = true;
            }
        });

        document.addEventListener('click', (event) => {
            if (!wrap.contains(event.target)) list.hidden = true;
        });

        return { paint, suggest: list };
    }

    global.PhinsApplySuggest = {
        DIAL_CODES,
        COUNTRIES,
        CITIES,
        OCCUPATIONS,
        MEDICATIONS,
        suggest,
        attach,
        composePhone,
        parsePhone,
        defaultDial,
        formatDial,
        digitsOnly,
    };
}(window));
