import React, { useState, useEffect } from 'react';
import { 
  Cloud, Newspaper, TrendingUp, Settings, MapPin, 
  Rocket, DollarSign, Calendar, Info, Languages, 
  Thermometer, Wind, Droplets, Sun, AlertTriangle 
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import './App.css';

const API_URL = "/api";

function App() {
  const [activeTab, setActiveTab] = useState('dashboard');
  const [weather, setWeather] = useState(null);
  const [user, setUser] = useState({
    id: 1, // Placeholder for actual user session
    home_city: 'Moscow',
    units: 'metric',
    lang: 'ru',
    favorites: []
  });
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetchUserData();
  }, []);

  useEffect(() => {
    if (user.home_city) {
      fetchWeather(user.home_city);
    }
  }, [user.home_city, user.units, user.lang]);

  const fetchUserData = async () => {
    try {
      const resp = await fetch(`${API_URL}/user/${user.id}`);
      const data = await resp.json();
      setUser(prev => ({ ...prev, ...data }));
    } catch (e) {
      console.error("Failed to fetch user data", e);
    }
  };

  const fetchWeather = async (city) => {
    setLoading(true);
    try {
      const response = await fetch(`${API_URL}/weather/details/${city}?units=${user.units}&lang=${user.lang}`);
      const data = await response.json();
      setWeather(data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const updateSettings = async (updates) => {
    try {
      const response = await fetch(`${API_URL}/user/${user.id}/settings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates)
      });
      if (response.ok) {
        setUser(prev => ({ ...prev, ...updates }));
      }
    } catch (e) {
      console.error("Failed to update settings", e);
    }
  };

  return (
    <div className="app-container">
      {/* Sidebar */}
      <aside className="sidebar glass-card">
        <div className="sidebar-brand">
          <div className="brand-logo">
            <Cloud size={24} color="white" />
          </div>
          <h2>SkyPulse</h2>
        </div>

        <nav className="sidebar-nav">
          <NavItem active={activeTab === 'dashboard'} icon={<TrendingUp size={20}/>} label="Обзор" onClick={() => setActiveTab('dashboard')} />
          <NavItem active={activeTab === 'news'} icon={<Newspaper size={20}/>} label="Новости" onClick={() => setActiveTab('news')} />
          <NavItem active={activeTab === 'space'} icon={<Rocket size={20}/>} label="Космос" onClick={() => setActiveTab('space')} />
          <NavItem active={activeTab === 'finance'} icon={<DollarSign size={20}/>} label="Финансы" onClick={() => setActiveTab('finance')} />
          <NavItem active={activeTab === 'calendar'} icon={<Calendar size={20}/>} label="Календарь" onClick={() => setActiveTab('calendar')} />
        </nav>

        <div className="sidebar-footer">
          <NavItem active={activeTab === 'settings'} icon={<Settings size={20}/>} label="Настройки" onClick={() => setActiveTab('settings')} />
        </div>
      </aside>

      {/* Main Content */}
      <main className="main-content">
        <header className="main-header">
          <h1 className="header-title">
            {activeTab === 'dashboard' && 'Обзор'}
            {activeTab === 'news' && 'Новости'}
            {activeTab === 'space' && 'Космический Пульс'}
            {activeTab === 'finance' && 'Финансовый Пульс'}
            {activeTab === 'calendar' && 'Календарь'}
            {activeTab === 'settings' && 'Настройки'}
          </h1>
          <div className="location-badge glass-card">
             <MapPin size={16} color="var(--accent-primary)" />
             <span>{weather?.city || user.home_city}</span>
          </div>
        </header>

        <AnimatePresence mode="wait">
          <motion.div
            key={activeTab}
            initial={{ opacity: 0, scale: 0.98 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 1.02 }}
            transition={{ duration: 0.2 }}
            className="view-wrapper"
          >
            {activeTab === 'dashboard' && <Dashboard weather={weather} />}
            {activeTab === 'news' && <NewsFeed />}
            {activeTab === 'space' && <SpaceView />}
            {activeTab === 'finance' && <FinanceView />}
            {activeTab === 'calendar' && <CalendarView />}
            {activeTab === 'settings' && <SettingsView user={user} onUpdate={updateSettings} />}
          </motion.div>
        </AnimatePresence>
      </main>
    </div>
  );
}

const NavItem = ({ active, icon, label, onClick }) => (
  <div className={`nav-item ${active ? 'active' : ''}`} onClick={onClick}>
    <div className="nav-icon">{icon}</div>
    <span className="nav-label">{label}</span>
  </div>
);

// --- Sub-Views ---

const Dashboard = ({ weather }) => {
  if (!weather) return <div className="loading">Загрузка данных...</div>;

  return (
    <div className="dashboard-layout">
      {/* Current Weather High-level */}
      <div className="main-weather glass-card highlight">
        <div className="weather-primary">
          <div className="temp-large">
            {Math.round(weather.current.temp)}°
          </div>
          <div className="weather-meta">
            <span className="weather-desc">{weather.current.description}</span>
            <div className="weather-sub">
              <span>{weather.city}</span>
            </div>
          </div>
        </div>
        <div className="weather-badges">
          <div className="mini-badge">
            <Sun size={14} />
            <span>UV: {weather.uv.match(/\d+/)?.[0] || '0'}</span>
          </div>
          <div className="mini-badge">
            <Wind size={14} />
            <span>AQI: {weather.air_quality?.match(/(\d)\/5/)?.[1] || '1'}</span>
          </div>
        </div>
      </div>

      {/* Metrics Grid */}
      <div className="metrics-grid">
        <MetricCard title="Одежда" content={weather.clothing} icon={<Thermometer size={20}/>} />
        <MetricCard title="Качество воздуха" content={weather.air_quality} icon={<Wind size={20}/>} smallText />
        <MetricCard title="UV индекс" content={weather.uv} icon={<Sun size={20}/>} smallText />
        {weather.alerts && <MetricCard title="Внимание" content={weather.alerts} icon={<AlertTriangle size={20}/>} variant="error" />}
      </div>

      {/* Temp Chart Section */}
      {weather.chart && (
        <div className="glass-card full-width">
          <h3 className="section-title"><Info size={16}/> Прогноз на 24ч</h3>
          <pre className="chart-pre">{weather.chart}</pre>
        </div>
      )}

      {/* Radar Link */}
      <a href={weather.radar_url} target="_blank" rel="noreferrer" className="radar-link glass-card">
         <div className="radar-content">
            <h3>🌧 Карта осадков</h3>
            <p>Смотреть движение туч на RainViewer</p>
         </div>
         <div className="radar-arrow">→</div>
      </a>
    </div>
  );
};

const SafeHTML = ({ html }) => {
  if (!html) return null;
  const parts = html.split(/(<[^>]+>)/g);
  return (
    <>
      {parts.map((part, i) => {
        if (part === '<br/>' || part === '<br>') return <br key={i} />;
        if (part === '<b>') return null; // handled by next part
        if (part === '</b>') return null;
        if (part === '<i>') return null;
        if (part === '</i>') return null;

        // Check if previous part was <b> or <i>
        const prev = parts[i-1];
        if (prev === '<b>') return <b key={i}>{part}</b>;
        if (prev === '<i>') return <i key={i}>{part}</i>;
        
        return part;
      }).filter(p => p !== null)}
    </>
  );
};

const MetricCard = ({ title, content, icon, variant = "default", smallText = false }) => (
  <div className={`metric-card glass-card ${variant}`}>
    <div className="metric-header">
      {icon}
      <h4>{title}</h4>
    </div>
    <div className={`metric-body ${smallText ? 'small-text' : ''}`}>
      <SafeHTML html={content.replace(/\n/g, '<br/>')} />
    </div>
  </div>
);

const NewsFeed = () => {
  const [news, setNews] = useState([]);
  const [category, setCategory] = useState('general');
  const [loading, setLoading] = useState(false);

  const categories = [
    { id: 'general', label: 'Главное' },
    { id: 'technology', label: 'IT' },
    { id: 'business', label: 'Бизнес' },
    { id: 'sports', label: 'Спорт' },
    { id: 'science', label: 'Наука' }
  ];

  useEffect(() => {
    fetchNews();
  }, [category]);

  const fetchNews = async () => {
    setLoading(true);
    try {
      const response = await fetch(`${API_URL}/news?category=${category}`);
      const data = await response.json();
      setNews(data.news);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="view-container">
      <div className="category-tags">
        {categories.map(cat => (
          <button 
            key={cat.id} 
            className={`tag-btn ${category === cat.id ? 'active' : ''}`}
            onClick={() => setCategory(cat.id)}
          >
            {cat.label}
          </button>
        ))}
      </div>
      <div className="news-list">
        {loading ? <div className="loading">Загружаю...</div> : news.map((item, i) => (
          <div key={i} className="news-item glass-card card-hover">
            <div className="news-header">
              <h4>{item.title}</h4>
              <span className="news-source">{item.source}</span>
            </div>
            <div className="news-footer">
               <a href={item.link} target="_blank" rel="noreferrer">Подробнее</a>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

const SpaceView = () => {
  const [articles, setArticles] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const fetchSpace = async () => {
      setLoading(true);
      try {
        const resp = await fetch(`${API_URL}/space/news`);
        const data = await resp.json();
        setArticles(data.articles);
      } catch (e) { console.error(e); }
      finally { setLoading(false); }
    };
    fetchSpace();
  }, []);

  return (
    <div className="view-container">
      <div className="space-list">
        {articles.map((art, i) => (
          <div key={i} className="space-card glass-card card-hover">
            {art.image_url && <img src={art.image_url} alt={art.title} className="card-img" />}
            <div className="card-content">
              <h3>{art.title}</h3>
              <p>{art.summary?.slice(0, 150)}...</p>
              <div className="card-footer">
                <span>{art.news_site}</span>
                <a href={art.url} target="_blank" rel="noreferrer">NASA Space →</a>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

const FinanceView = () => {
  const [rates, setRates] = useState(null);

  useEffect(() => {
    fetch(`${API_URL}/finance/rates`)
      .then(r => r.json())
      .then(setRates);
  }, []);

  if (!rates) return <div className="loading">Загрузка котировок...</div>;

  return (
    <div className="view-container">
      <div className="finance-grid">
        <FinanceCard label="Доллар" value={rates.USD} symbol="$" color="success" />
        <FinanceCard label="Евро" value={rates.EUR} symbol="€" color="info" />
        <FinanceCard label="Юань" value={rates.CNY} symbol="¥" color="warning" />
      </div>
      <div className="glass-card info-banner" style={{ marginTop: '20px' }}>
         <Info size={18} />
         <p>Курсы валют обновляются в реальном времени через ExchangeRate-API.</p>
      </div>
    </div>
  );
};

const FinanceCard = ({ label, value, symbol, color }) => (
  <div className={`finance-card glass-card ${color}`}>
    <span className="finance-label">{label}</span>
    <div className="finance-row">
      <span className="finance-symbol">{symbol}</span>
      <span className="finance-value">{value.toFixed(2)}</span>
      <span className="finance-currency">₽</span>
    </div>
  </div>
);

const CalendarView = () => {
  const [holidays, setHolidays] = useState([]);

  useEffect(() => {
    fetch(`${API_URL}/calendar/holidays`)
      .then(r => r.json())
      .then(data => setHolidays(data.holidays));
  }, []);

  return (
    <div className="view-container">
      <div className="holiday-list">
        <h3 className="section-title">🎆 Предстоящие праздники (РФ)</h3>
        {holidays.length > 0 ? holidays.map((h, i) => (
          <div key={i} className="holiday-item glass-card">
            <div className="holiday-date">
              {new Date(h.date).toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })}
            </div>
            <div className="holiday-name">{h.localName}</div>
          </div>
        )) : <div className="loading">Загрузка календаря...</div>}
      </div>
    </div>
  );
};

const SettingsView = ({ user, onUpdate }) => {
  const [city, setCity] = useState(user.home_city);

  return (
    <div className="view-container">
      <div className="settings-layout">
        <div className="settings-section glass-card">
          <h3><MapPin size={18}/> Мой город</h3>
          <div className="input-row">
            <input 
              type="text" 
              value={city} 
              onChange={(e) => setCity(e.target.value)} 
              className="glass-input"
            />
            <button onClick={() => onUpdate({ home_city: city })} className="action-btn">Сохранить</button>
          </div>
        </div>

        <div className="settings-section glass-card">
          <h3><Languages size={18}/> Язык интерфейса</h3>
          <div className="btn-group">
            <button className={user.lang === 'ru' ? 'active' : ''} onClick={() => onUpdate({ lang: 'ru' })}>Русский</button>
            <button className={user.lang === 'en' ? 'active' : ''} onClick={() => onUpdate({ lang: 'en' })}>English</button>
          </div>
        </div>

        <div className="settings-section glass-card">
          <h3><Thermometer size={18}/> Единицы измерения</h3>
          <div className="btn-group">
            <button className={user.units === 'metric' ? 'active' : ''} onClick={() => onUpdate({ units: 'metric' })}>Цельсий (°C)</button>
            <button className={user.units === 'imperial' ? 'active' : ''} onClick={() => onUpdate({ units: 'imperial' })}>Фаренгейт (°F)</button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default App;
