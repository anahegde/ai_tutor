import React, { useEffect } from 'react'
import {
  View,
  StyleSheet,
  FlatList,
  ListRenderItem,
} from 'react-native'

import {
  LiveKitRoom,
  AudioSession,
  useTracks,
  isTrackReference,
  TrackReferenceOrPlaceholder,
  VideoTrack,
  AudioTrack,
} from '@livekit/react-native'

import { Track } from 'livekit-client'

// ============================================================================
// CONFIG
// ============================================================================

const LIVEKIT_URL = 'wss://demo-bzp2olpx.livekit.cloud'
const TOKEN =
  'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjE3Njc5MTczNzcsImlkZW50aXR5IjoidGVzdC1hZ2VudCIsImlzcyI6IkFQSTdWZ1RyOERDWGdENiIsIm5iZiI6MTc2NzAxNzM3Nywic3ViIjoidGVzdC1hZ2VudCIsInZpZGVvIjp7ImNhblB1Ymxpc2giOnRydWUsImNhblB1Ymxpc2hEYXRhIjp0cnVlLCJjYW5TdWJzY3JpYmUiOnRydWUsInJvb20iOiJ0ZXN0LWFnZW50Iiwicm9vbUpvaW4iOnRydWV9fQ.-ItPwwiomE9vWmHDWS4nEoEXzQr_5Ux4MgiZzBRyMQQ'

// ============================================================================
// MAIN SCREEN
// ============================================================================

const AIScreen: React.FC = () => {
  useEffect(() => {
    // 🔊 REQUIRED FOR AUDIO (2.9.6)
    AudioSession.startAudioSession({
      android: {
        audioType: 'speech',
        speakerOn: true,
      },
      ios: {
        defaultToSpeaker: true,
      },
    })

    return () => {
      AudioSession.stopAudioSession()
    }
  }, [])

  return (
    <LiveKitRoom
      serverUrl={LIVEKIT_URL}
      token={TOKEN}
      connect={true}
      audio={true}
      video={true}
    >
      <RoomView />
    </LiveKitRoom>
  )
}

// ============================================================================
// ROOM VIEW
// ============================================================================

const RoomView: React.FC = () => {
  // 🔊 Subscribe to AUDIO + VIDEO tracks
  const tracks = useTracks([
    Track.Source.Microphone,
    Track.Source.Camera,
  ])

  const renderItem: ListRenderItem<TrackReferenceOrPlaceholder> = ({ item }) => {
    if (!isTrackReference(item)) return null

    if (item.source === Track.Source.Camera) {
      return (
        <VideoTrack
          trackRef={item}
          style={styles.video}
        />
      )
    }

    if (item.source === Track.Source.Microphone) {
      // 🔊 THIS IS WHAT PLAYS AUDIO
      return <AudioTrack trackRef={item} />
    }

    return null
  }

  return (
    <View style={styles.container}>
      <FlatList
        data={tracks}
        renderItem={renderItem}
        keyExtractor={(item) =>
          isTrackReference(item)
            ? `${item.participant.identity}-${item.source}`
            : Math.random().toString()
        }
      />
    </View>
  )
}

// ============================================================================
// STYLES
// ============================================================================

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#000',
  },
  video: {
    width: '100%',
    height: 300,
  },
})

export default AIScreen