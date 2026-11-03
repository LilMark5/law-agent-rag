interface BadgeProps {
  domain: string;
  domain_zh: string;
}

export function DomainBadge({ domain, domain_zh }: BadgeProps) {
  return <span className={`domain-badge ${domain}`}>{domain_zh}</span>;
}
