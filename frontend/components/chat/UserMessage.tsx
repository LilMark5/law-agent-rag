interface UserMessageProps {
  content: string;
}

export function UserMessage({ content }: UserMessageProps) {
  return (
    <div className="msg msg-user">
      <span className="msg-meta">我</span>
      <div className="msg-user-bubble">{content}</div>
    </div>
  );
}
