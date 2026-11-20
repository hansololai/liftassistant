import React from 'react';
import { Tooltip, Badge } from '@mantine/core';
import { IconMan, IconWoman, IconMoodKid, IconUsers, IconUser } from '@tabler/icons-react';

interface PersonBadgeProps {
  person: string;
  size?: 'xs' | 'sm';
  withLabel?: boolean;
}

export const getPersonConfig = (person: string) => {
  const p = person.trim().toLowerCase();
  if (p === 'dad') {
    return {
      label: 'Dad',
      icon: IconMan,
      color: 'blue',
    };
  }
  if (p === 'mom') {
    return {
      label: 'Mom',
      icon: IconWoman,
      color: 'pink',
    };
  }
  if (p === 'marcus' || p === 'leo' || p === 'kid' || p === 'child') {
    return {
      label: person.trim(),
      icon: IconMoodKid,
      color: 'teal',
    };
  }
  if (p === 'family') {
    return {
      label: 'Family',
      icon: IconUsers,
      color: 'indigo',
    };
  }
  return {
    label: person.trim(),
    icon: IconUser,
    color: 'gray',
  };
};

export const PersonBadge: React.FC<PersonBadgeProps> = ({ person, size = 'xs', withLabel = true }) => {
  const cfg = getPersonConfig(person);
  const IconComponent = cfg.icon;
  const iconSize = size === 'xs' ? 11 : 13;

  if (!withLabel) {
    return (
      <Tooltip label={cfg.label} withArrow position="top">
        <Badge
          size={size}
          color={cfg.color}
          variant="light"
          p={3}
          style={{ cursor: 'pointer', minWidth: 18, height: 18, display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
        >
          <IconComponent size={iconSize} />
        </Badge>
      </Tooltip>
    );
  }

  return (
    <Badge
      size={size}
      color={cfg.color}
      variant="light"
      leftSection={<IconComponent size={iconSize} />}
      style={{ textTransform: 'none' }}
    >
      {cfg.label}
    </Badge>
  );
};
