import { useState, useEffect } from 'react';
import './App.css';

function App() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [sessionId, setSessionId] = useState('');

  // Generate a unique session ID for budget tracking when the app loads
  // FIXED: Replaced crypto.randomUUID() with standard Math randomizer
  useEffect(() => {
    setSessionId(Math.random().toString(36).substring(2, 15));
  }, []);

  const sendMessage = async (e) => {
    e.preventDefault();
    if (!input.trim()) return;

    const userMessage = { role: 'user', content: input };
    setMessages((prev) => [...prev, userMessage]);
    setInput('');
    setIsLoading(true);

    try {
      // FIXED: Pointed directly to AWS EC2 Public IP and added port 8000
      const response = await fetch('http://13.238.254.128:8000/v1/chat/completions', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer sk-PlBfkdUUCz4InH_zs_INpQ',
          'team_id': '37c9a0cf-9832-486f-af0e-b357daf2f9ed',
          'agent_id': 'agent-code-reviewer',
          'x-session-id': sessionId,
        },
        body: JSON.stringify({
          model: 'gemini/gemini-3.6-flash',
          messages: [...messages, userMessage],
        }),
      });
      
      // ... (Your original response handling code here) ...

    } catch (error) {
      console.error(error);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="app-container">
      {/* FIXED: Replaced header with the new Analytics button layout */}
      <header className="chat-header">
        <div>
          <h1>AI Agent Interface</h1>
          <span className="session-badge">Session: {sessionId.slice(0, 8)}...</span>
        </div>
        <a 
          href="http://13.238.254.128:8501" 
          target="_blank" 
          rel="noopener noreferrer" 
          className="analytics-button"
        >
          Analytics
        </a>
      </header>
      
      {/* ... (Your original chat interface JSX here) ... */}
    </div>
  );
}

export default App;
