function App() {
  const [theme, setTheme] = useState("dark");
  const [text, setText] = useState("hi");

  return (
    <div className={`page ${theme}`}>
      <div className="header">
        <h1>Hey bro! 👋🔥 What's up?</h1>
        <div className="subtext">
          <p>What are we building today?</p>
        </div>
      </div>
      <PromptBar theme={theme} text={text} onChange={setText} />
    </div>
  )
}

function PromptBar({ theme, text, onChange }) {
  return (
    <div className="bar">
      <div className="left">
        <button className="add">+</button>
        <input className="input" type="text" value={text} readOnly />
      </div>
      <div className="right">
        <button className="think" aria-label="Think">
          <svg className="icon" viewBox="0 0 24 24" aria-hidden="true">
            <path
              d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-1.61 3.79-3.59 4.11z" fill="currentColor" />
          </svg>
          Think
        </button>
        <button className="mic" aria-label="Microphone">
          <svg className="icon" viewBox="0 0 24 20" aria-hidden="true">
            <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3zm6.31-6.83L12 12.59l-6.31-6.31L10.59 4 12 5.41l1.41-1.41L13.41 4z" fill="currentColor" />
          </svg>
        </button>
        <button className="send" aria-label="Send">
          <svg className="icon" viewBox="0 0 20 20" aria-hidden="true">
            <path d="M12 2L4 5v13.17c0 .75.29 1.45.78 2.01l7.22 7.22c.29.28.66.44 1.05.44s.76-.16 1.05-.44l7.22-7.22c.49-.56.78-1.26.78-2.01V5l-8-3z" fill="currentColor" />
          </svg>
        </button>
      </div>
    </div>
  )
}

export default App