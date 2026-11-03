import { useState } from "react";

interface InputAreaProps {
  onSend: (question: string) => void;
  disabled?: boolean;
}

export function InputArea({ onSend, disabled }: InputAreaProps) {
  const [input, setInput] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || disabled) return;
    onSend(input.trim());
    setInput("");
  };

  return (
    <form className="chat-input-form" onSubmit={handleSubmit}>
      <input
        className="chat-input"
        disabled={disabled}
        onChange={(e) => setInput(e.target.value)}
        placeholder="输入法律问题，例如：试用期解除的举证责任如何分配？"
        type="text"
        value={input}
      />
      <button
        className="chat-send"
        disabled={disabled || !input.trim()}
        type="submit"
      >
        发送
      </button>
    </form>
  );
}
