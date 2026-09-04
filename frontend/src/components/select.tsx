"use client";

import React, { useState, useRef, useEffect } from "react";
import { CaretDownIcon, CheckIcon } from "@phosphor-icons/react/dist/ssr";
import { AnimatePresence, motion } from "framer-motion";

export interface SelectOption {
  value: string;
  label: string;
  note?: string;
}

export interface SelectProps {
  id?: string;
  name?: string;
  value?: string;
  defaultValue?: string;
  options: SelectOption[];
  placeholder?: string;
  onChange?: (value: string) => void;
  disabled?: boolean;
  className?: string;
  size?: "default" | "sm";
}

export function Select({
  id,
  name,
  value,
  defaultValue = "",
  options,
  placeholder = "Select an option",
  onChange,
  disabled = false,
  className = "",
  size = "default",
}: SelectProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [internalValue, setInternalValue] = useState<string>(
    value !== undefined ? value : defaultValue
  );
  const containerRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  const selectedValue = value !== undefined ? value : internalValue;
  const selectedOption = options.find((opt) => opt.value === selectedValue);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (
        containerRef.current &&
        !containerRef.current.contains(event.target as Node)
      ) {
        setIsOpen(false);
      }
    }

    if (isOpen) {
      document.addEventListener("mousedown", handleClickOutside);
    }
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [isOpen]);

  function handleSelect(optionValue: string) {
    if (disabled) return;
    if (value === undefined) {
      setInternalValue(optionValue);
    }
    onChange?.(optionValue);
    setIsOpen(false);
    buttonRef.current?.focus();
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (disabled) return;

    if (e.key === "Escape") {
      setIsOpen(false);
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      if (!isOpen) {
        setIsOpen(true);
      } else {
        const currentIndex = options.findIndex(
          (opt) => opt.value === selectedValue
        );
        const nextIndex =
          currentIndex < options.length - 1 ? currentIndex + 1 : 0;
        handleSelect(options[nextIndex].value);
      }
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (!isOpen) {
        setIsOpen(true);
      } else {
        const currentIndex = options.findIndex(
          (opt) => opt.value === selectedValue
        );
        const prevIndex =
          currentIndex > 0 ? currentIndex - 1 : options.length - 1;
        handleSelect(options[prevIndex].value);
      }
    }
  }

  const isSmall = size === "sm";

  return (
    <div
      ref={containerRef}
      className={`relative w-full ${className}`}
      onKeyDown={handleKeyDown}
    >
      {/* Hidden input for standard forms and server actions */}
      {name && <input type="hidden" name={name} value={selectedValue} />}

      <button
        ref={buttonRef}
        id={id}
        type="button"
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={isOpen}
        onClick={() => !disabled && setIsOpen((prev) => !prev)}
        className={`group flex w-full items-center justify-between gap-2 border text-left transition-all duration-150 outline-none select-none ${
          isSmall ? "px-2.5 py-1 text-[12px]" : "px-3 py-2 text-[12.5px]"
        }`}
        style={{
          borderRadius: "var(--radius)",
          borderColor: isOpen ? "var(--flag)" : "var(--line)",
          background: isOpen ? "var(--surface-3)" : "var(--surface-2)",
          color: selectedOption ? "var(--ink)" : "var(--ink-3)",
          backdropFilter: "blur(16px)",
          WebkitBackdropFilter: "blur(16px)",
          boxShadow: isOpen
            ? "0 0 0 2px var(--flag-wash), inset 0 1px 0 rgba(255, 255, 255, 0.1)"
            : "0 4px 16px rgba(0, 0, 0, 0.25), inset 0 1px 0 rgba(255, 255, 255, 0.08)",
          cursor: disabled ? "not-allowed" : "pointer",
          opacity: disabled ? 0.5 : 1,
        }}
      >
        <span className="truncate">
          {selectedOption ? selectedOption.label : placeholder}
        </span>
        <CaretDownIcon
          size={isSmall ? 12 : 14}
          weight="bold"
          className="shrink-0 transition-transform duration-200"
          style={{
            transform: isOpen ? "rotate(180deg)" : "rotate(0deg)",
            color: isOpen ? "var(--flag)" : "var(--ink-3)",
          }}
        />
      </button>

      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ opacity: 0, y: -4, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -4, scale: 0.98 }}
            transition={{ duration: 0.14, ease: "easeOut" }}
            role="listbox"
            className="absolute top-full left-0 right-0 z-50 mt-1.5 p-1.5 overflow-y-auto max-h-64 border shadow-2xl"
            style={{
              background: "rgba(13, 17, 24, 0.94)",
              backdropFilter: "blur(24px)",
              WebkitBackdropFilter: "blur(24px)",
              borderColor: "rgba(255, 255, 255, 0.12)",
              borderRadius: "var(--radius)",
              boxShadow:
                "0 16px 40px -4px rgba(0, 0, 0, 0.75), 0 4px 16px -2px rgba(0, 0, 0, 0.5), inset 0 1px 0 rgba(255, 255, 255, 0.12)",
            }}
          >
            {placeholder && (
              <div
                role="option"
                aria-selected={selectedValue === ""}
                onClick={() => handleSelect("")}
                className="flex items-center justify-between px-3 py-2 text-[12px] cursor-pointer transition-colors duration-100"
                style={{
                  borderRadius: "calc(var(--radius) - 4px)",
                  background:
                    selectedValue === ""
                      ? "rgba(255, 255, 255, 0.08)"
                      : "transparent",
                  color: selectedValue === "" ? "var(--ink)" : "var(--ink-3)",
                }}
                onMouseEnter={(e) => {
                  if (selectedValue !== "") {
                    e.currentTarget.style.background = "rgba(255, 255, 255, 0.05)";
                    e.currentTarget.style.color = "var(--ink)";
                  }
                }}
                onMouseLeave={(e) => {
                  if (selectedValue !== "") {
                    e.currentTarget.style.background = "transparent";
                    e.currentTarget.style.color = "var(--ink-3)";
                  }
                }}
              >
                <span>{placeholder}</span>
                {selectedValue === "" && (
                  <CheckIcon size={14} weight="bold" style={{ color: "var(--flag)" }} />
                )}
              </div>
            )}

            {options.map((opt) => {
              const isSelected = opt.value === selectedValue;
              return (
                <div
                  key={opt.value}
                  role="option"
                  aria-selected={isSelected}
                  onClick={() => handleSelect(opt.value)}
                  className="flex items-center justify-between px-3 py-2 text-[12.5px] cursor-pointer transition-colors duration-100 my-0.5"
                  style={{
                    borderRadius: "calc(var(--radius) - 4px)",
                    background: isSelected
                      ? "rgba(0, 112, 243, 0.16)"
                      : "transparent",
                    color: isSelected ? "#ffffff" : "var(--ink)",
                    fontWeight: isSelected ? 500 : 400,
                  }}
                  onMouseEnter={(e) => {
                    if (!isSelected) {
                      e.currentTarget.style.background = "rgba(255, 255, 255, 0.07)";
                      e.currentTarget.style.color = "#ffffff";
                    }
                  }}
                  onMouseLeave={(e) => {
                    if (!isSelected) {
                      e.currentTarget.style.background = "transparent";
                      e.currentTarget.style.color = "var(--ink)";
                    }
                  }}
                >
                  <div className="flex flex-col min-w-0 pr-2">
                    <span className="truncate">{opt.label}</span>
                    {opt.note && (
                      <span className="text-[11px] text-[var(--ink-3)] truncate">
                        {opt.note}
                      </span>
                    )}
                  </div>
                  {isSelected && (
                    <CheckIcon
                      size={14}
                      weight="bold"
                      className="shrink-0"
                      style={{ color: "var(--flag)" }}
                    />
                  )}
                </div>
              );
            })}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
