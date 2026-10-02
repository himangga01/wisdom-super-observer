"use client";
import { AccountFlowForm, type AccountFlowFormProps } from "./AccountFlowForm";
export function RegisterForm(props: AccountFlowFormProps) {
  return <AccountFlowForm {...props} purpose="register" />;
}
