import { useState, useCallback, useMemo } from 'react';
import { Modal, Input } from 'antd';

interface UsePromptModalReturn {
  showPrompt: (title: string, placeholder?: string) => Promise<string | null>;
  PromptModal: () => React.ReactNode;
}

export function usePromptModal(): UsePromptModalReturn {
  const [state, setState] = useState<{
    visible: boolean;
    title: string;
    placeholder: string;
    value: string;
    resolve: ((value: string | null) => void) | null;
  }>({
    visible: false,
    title: '',
    placeholder: '',
    value: '',
    resolve: null,
  });

  const showPrompt = useCallback((title: string, placeholder: string = ''): Promise<string | null> => {
    return new Promise((resolve) => {
      setState({ visible: true, title, placeholder, value: '', resolve });
    });
  }, []);

  const handleOk = useCallback(() => {
    state.resolve?.(state.value || null);
    setState((s) => ({ ...s, visible: false, resolve: null }));
  }, [state.resolve, state.value]);

  const handleCancel = useCallback(() => {
    state.resolve?.(null);
    setState((s) => ({ ...s, visible: false, resolve: null }));
  }, [state.resolve]);

  const PromptModal = useMemo(() => {
    return function PromptModalComponent() {
      return (
        <Modal
          title={state.title}
          open={state.visible}
          onOk={handleOk}
          onCancel={handleCancel}
          okText="确定"
          cancelText="取消"
        >
          <Input.TextArea
            autoFocus
            placeholder={state.placeholder}
            value={state.value}
            onChange={(e) => setState((s) => ({ ...s, value: e.target.value }))}
            rows={4}
            onPressEnter={(e) => {
              if (!e.shiftKey) {
                e.preventDefault();
                handleOk();
              }
            }}
          />
        </Modal>
      );
    };
  }, [state.title, state.visible, state.placeholder, state.value, handleOk, handleCancel]);

  return { showPrompt, PromptModal };
}
