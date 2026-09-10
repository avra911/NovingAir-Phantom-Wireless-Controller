import {
  Tabs,
  TabList,
  TabTrigger,
  TabSlot,
} from 'expo-router/ui';

export default function AppTabs() {
  return (
    <Tabs>
      <TabList style={{ display: 'none' }}>
        <TabTrigger name="index" href="/" />
      </TabList>

      <TabSlot style={{ height: '100%' }} />
    </Tabs>
  );
}