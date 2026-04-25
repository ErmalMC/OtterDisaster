export function Otter({ className }) {
  return (
    <svg
      className={className}
      viewBox="0 0 120 80"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-label="Ollie the otter"
    >
      {/* Body floating on back */}
      <ellipse cx="60" cy="48" rx="42" ry="14" fill="#8B6F5C" />
      <ellipse cx="60" cy="46" rx="38" ry="11" fill="#A0856F" />
      {/* Belly */}
      <ellipse cx="60" cy="46" rx="28" ry="7" fill="#D4B89A" opacity="0.6" />
      {/* Head */}
      <circle cx="22" cy="40" r="13" fill="#8B6F5C" />
      <circle cx="22" cy="42" r="10" fill="#A0856F" />
      {/* Ears */}
      <circle cx="14" cy="32" r="3" fill="#6B5444" />
      <circle cx="28" cy="31" r="3" fill="#6B5444" />
      {/* Eyes */}
      <circle cx="18" cy="40" r="1.4" fill="#1A1110" />
      <circle cx="26" cy="40" r="1.4" fill="#1A1110" />
      <circle cx="18.4" cy="39.6" r="0.4" fill="#fff" />
      <circle cx="26.4" cy="39.6" r="0.4" fill="#fff" />
      {/* Nose */}
      <ellipse cx="22" cy="44" rx="1.6" ry="1.1" fill="#1A1110" />
      {/* Whiskers */}
      <line x1="14" y1="44" x2="8" y2="43" stroke="#6B5444" strokeWidth="0.5" />
      <line x1="14" y1="45" x2="8" y2="46" stroke="#6B5444" strokeWidth="0.5" />
      <line
        x1="30"
        y1="44"
        x2="36"
        y2="43"
        stroke="#6B5444"
        strokeWidth="0.5"
      />
      <line
        x1="30"
        y1="45"
        x2="36"
        y2="46"
        stroke="#6B5444"
        strokeWidth="0.5"
      />
      {/* Paws holding device on belly */}
      <ellipse cx="55" cy="40" rx="4" ry="3" fill="#6B5444" />
      <ellipse cx="68" cy="40" rx="4" ry="3" fill="#6B5444" />
      {/* Sensor device on belly */}
      <rect x="56" y="36" width="12" height="6" rx="1.5" fill="#1E293B" />
      <circle cx="62" cy="39" r="1" fill="#7DD3FC">
        <animate
          attributeName="opacity"
          values="1;0.3;1"
          dur="1.6s"
          repeatCount="indefinite"
        />
      </circle>
      {/* Tail */}
      <path d="M 100 48 Q 115 44 118 50 Q 115 52 100 52 Z" fill="#6B5444" />
      {/* Water ripples */}
      <ellipse cx="60" cy="62" rx="44" ry="2" fill="#7DD3FC" opacity="0.3" />
      <ellipse cx="60" cy="65" rx="36" ry="1.5" fill="#7DD3FC" opacity="0.2" />
    </svg>
  );
}
